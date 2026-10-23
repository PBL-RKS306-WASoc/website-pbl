import logging
from datetime import timedelta

from flask import (Blueprint, abort, flash, redirect, render_template, request, session,
                   url_for)
from flask_login import current_user, logout_user
from sqlalchemy import func, or_

from ..extensions import db
from ..logging_setup import log_event
from ..models import Order, User, utcnow
from .payments import _ctx, admin_required
from .user_forms import ActionForm, LockForm, ReasonForm, RoleForm

bp = Blueprint("admin_users", __name__, url_prefix="/admin/users")

W = logging.WARNING
ROLES = ("customer", "admin")
PER_PAGE = 25


# ---------- penegakan status akun untuk SEMUA request ----------
@bp.before_app_request
def enforce_account_status():
    """Sesi milik akun yang dinonaktifkan/dikunci diakhiri pada request berikutnya.
    Catatan: Flask-Login menganggap user non-aktif sebagai tidak terautentikasi, jadi
    id user dibaca langsung dari sesi (current_user akan terlihat anonim)."""
    if request.endpoint == "static":
        return
    uid = session.get("_user_id")
    if not uid:
        return
    try:
        u = db.session.get(User, int(uid))
    except (TypeError, ValueError):
        return
    if u is not None and not u.is_active:
        log_event("auth.session_revoked", level=W, user_id=u.id, username=u.username,
                  reason="disabled" if not u.is_enabled else "locked",
                  src_ip=request.remote_addr, method=request.method, path=request.path)
        logout_user()
        flash("Sesi diakhiri: akun dinonaktifkan atau dikunci sementara.", "danger")
        return redirect(url_for("auth.login"))


# ---------- daftar & detail ----------
@bp.route("/")
@admin_required
def index():
    q = request.args.get("q", "").strip()[:50]
    role = request.args.get("role", "all")
    query = User.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(User.username.ilike(like), User.email.ilike(like)))
    if role in ROLES:
        query = query.filter(User.role == role)
    else:
        role = "all"
    page = max(request.args.get("page", 1, type=int), 1)
    pag = query.order_by(User.id).paginate(page=page, per_page=PER_PAGE, error_out=False)
    return render_template("admin/user_list.html", pag=pag, q=q, role=role, roles=ROLES,
                           args=dict(q=q, role=role))


@bp.route("/<int:user_id>")
@admin_required
def detail(user_id):
    u = db.session.get(User, user_id)
    if not u:
        abort(404)
    n_orders, paid_total = db.session.query(
        func.count(Order.id),
        func.coalesce(func.sum(db.case((Order.status == "paid", Order.total_idr), else_=0)), 0)
    ).filter(Order.user_id == u.id).one()
    return render_template("admin/user_detail.html", u=u, n_orders=n_orders,
                           paid_total=int(paid_total), is_self=(u.id == current_user.id),
                           role_form=RoleForm(role=u.role), lock_form=LockForm(minutes=60),
                           reason_form=ReasonForm(), action_form=ActionForm())


# ---------- aksi ----------
def _target(user_id, action):
    u = db.session.get(User, user_id)
    if not u:
        abort(404)
    if u.id == current_user.id:  # cegah admin mengunci/menurunkan diri sendiri
        log_event("admin.user_action_denied", level=W, action=action, reason="self_action",
                  target_user_id=u.id, **_ctx())
        flash("Anda tidak dapat melakukan aksi ini pada akun sendiri.", "danger")
        return None
    return u


def _back(u_id):
    return redirect(url_for("admin_users.detail", user_id=u_id))


def _log(event, u, level=logging.INFO, **extra):
    log_event(event, level=level, target_user_id=u.id, target_username=u.username,
              **extra, **_ctx())


@bp.route("/<int:user_id>/role", methods=["POST"])
@admin_required
def set_role(user_id):
    u = _target(user_id, "set_role")
    if u is None:
        return _back(user_id)
    form = RoleForm()
    if not form.validate_on_submit() or form.role.data not in ROLES:
        flash("Role tidak valid.", "danger")
        return _back(user_id)
    old, new = u.role, form.role.data
    if old == new:
        flash("Role tidak berubah.", "info")
        return _back(user_id)
    u.role = new
    db.session.commit()
    # Kenaikan ke admin = eskalasi hak akses -> WARNING agar mudah dikorelasi di SIEM
    _log("admin.user_role_changed", u, level=W if new == "admin" else logging.INFO,
         old_role=old, new_role=new)
    flash(f"Role {u.username} diubah menjadi {new}.", "success")
    return _back(user_id)


@bp.route("/<int:user_id>/disable", methods=["POST"])
@admin_required
def disable(user_id):
    u = _target(user_id, "disable")
    if u is None:
        return _back(user_id)
    form = ReasonForm()
    if not form.validate_on_submit():
        flash("Input tidak valid.", "danger")
        return _back(user_id)
    u.is_enabled = False
    u.lock_reason = (form.reason.data or "disabled_by_admin")[:200]
    db.session.commit()
    _log("admin.user_disabled", u, level=W, reason=u.lock_reason)
    flash(f"Akun {u.username} dinonaktifkan.", "success")
    return _back(user_id)


@bp.route("/<int:user_id>/enable", methods=["POST"])
@admin_required
def enable(user_id):
    u = _target(user_id, "enable")
    if u is None:
        return _back(user_id)
    if not ActionForm().validate_on_submit():
        abort(400)
    u.is_enabled = True
    if not u.is_locked:
        u.lock_reason = None
    db.session.commit()
    _log("admin.user_enabled", u)
    flash(f"Akun {u.username} diaktifkan.", "success")
    return _back(user_id)


@bp.route("/<int:user_id>/lock", methods=["POST"])
@admin_required
def lock(user_id):
    u = _target(user_id, "lock")
    if u is None:
        return _back(user_id)
    form = LockForm()
    if not form.validate_on_submit():
        flash("Durasi tidak valid (1 - 10080 menit).", "danger")
        return _back(user_id)
    u.locked_until = utcnow() + timedelta(minutes=form.minutes.data)
    u.lock_reason = (form.reason.data or "locked_by_admin")[:200]
    db.session.commit()
    _log("admin.user_locked", u, level=W, minutes=form.minutes.data, reason=u.lock_reason)
    flash(f"Akun {u.username} dikunci {form.minutes.data} menit.", "success")
    return _back(user_id)


@bp.route("/<int:user_id>/unlock", methods=["POST"])
@admin_required
def unlock(user_id):
    u = _target(user_id, "unlock")
    if u is None:
        return _back(user_id)
    if not ActionForm().validate_on_submit():
        abort(400)
    u.locked_until = None
    if u.is_enabled:
        u.lock_reason = None
    db.session.commit()
    _log("admin.user_unlocked", u)
    flash(f"Kunci akun {u.username} dibuka.", "success")
    return _back(user_id)