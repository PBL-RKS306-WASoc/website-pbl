import logging
from functools import wraps

from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, session, url_for)
from flask_login import current_user

from ..extensions import db
from ..logging_setup import log_event
from ..models import Order, Payment, User, utcnow
from .payment_forms import PaymentReviewForm

bp = Blueprint("admin_payments", __name__, url_prefix="/admin/payments")

W = logging.WARNING
STATUSES = ("waiting", "approved", "rejected")


def _sid():
    return (session.get("_id") or "")[:16]


def _ctx():
    return dict(admin_id=current_user.id, admin_username=current_user.username,
                src_ip=request.remote_addr, method=request.method,
                path=request.path, session_id=_sid())


def admin_required(fn):
    # Jika admin/__init__.py sudah punya decorator serupa, ganti dengan import dari sana
    # supaya nama event log seragam.
    @wraps(fn)
    def wrapper(*a, **kw):
        if not current_user.is_authenticated:
            log_event("admin.unauthenticated_access", level=W, src_ip=request.remote_addr,
                      method=request.method, path=request.path, session_id=_sid())
            return current_app.login_manager.unauthorized()
        if not current_user.is_admin:
            log_event("admin.unauthorized_access", level=W, user_id=current_user.id,
                      username=current_user.username, src_ip=request.remote_addr,
                      method=request.method, path=request.path, session_id=_sid())
            abort(403)
        return fn(*a, **kw)
    return wrapper


@bp.app_context_processor
def inject_waiting_count():
    if current_user.is_authenticated and current_user.is_admin:
        return {"waiting_payments_count":
                Payment.query.filter_by(status="waiting").count()}
    return {"waiting_payments_count": 0}


def _reviewable(order):
    return bool(order.payment and order.payment.status == "waiting"
                and order.status == "waiting_verification")


@bp.route("/")
@admin_required
def index():
    status = request.args.get("status", "waiting")
    q = (db.session.query(Payment, Order, User)
         .join(Order, Payment.order_id == Order.id)
         .join(User, Order.user_id == User.id))
    if status in STATUSES:
        q = q.filter(Payment.status == status)
    else:
        status = "all"
    ordering = Payment.uploaded_at.asc() if status == "waiting" else Payment.uploaded_at.desc()
    rows = q.order_by(ordering).limit(200).all()
    return render_template("admin/payment_list.html", rows=rows, status=status,
                           statuses=STATUSES)


@bp.route("/<int:order_id>")
@admin_required
def detail(order_id):
    order = db.session.get(Order, order_id)
    if not order or not order.payment:
        abort(404)
    payment = order.payment
    reviewer = db.session.get(User, payment.reviewed_by) if payment.reviewed_by else None
    return render_template("admin/payment_detail.html", order=order, payment=payment,
                           customer=order.user, reviewer=reviewer,
                           reviewable=_reviewable(order), form=PaymentReviewForm())


def _review(order_id, decision):
    form = PaymentReviewForm()
    if not form.validate_on_submit():
        flash("Input tidak valid.", "danger")
        return redirect(url_for("admin_payments.detail", order_id=order_id))

    # Kunci baris pembayaran agar dua admin tidak memproses bersamaan
    payment = Payment.query.filter_by(order_id=order_id).with_for_update().first()
    order = db.session.get(Order, order_id)
    if not payment or not order:
        db.session.rollback()
        abort(404)

    if payment.status != "waiting" or order.status != "waiting_verification":
        db.session.rollback()
        log_event("admin.payment_review_invalid", level=W, order_id=order_id,
                  decision=decision, payment_status=payment.status,
                  order_status=order.status, **_ctx())
        flash("Pembayaran ini sudah diproses atau tidak berstatus menunggu.", "warning")
        return redirect(url_for("admin_payments.detail", order_id=order_id))

    approve = decision == "approve"
    previous = order.status
    payment.status = "approved" if approve else "rejected"
    payment.reviewed_by = current_user.id
    payment.reviewed_at = utcnow()
    # Ditolak -> pesanan kembali menunggu pembayaran agar customer bisa unggah ulang
    order.status = "paid" if approve else "pending_payment"
    db.session.commit()

    fields = dict(order_id=order_id, customer_id=order.user_id, total_idr=order.total_idr,
                  previous_status=previous, new_status=order.status, **_ctx())
    if not approve:
        fields["reason"] = (form.reason.data or "")[:200]
    log_event("admin.payment_approved" if approve else "admin.payment_rejected", **fields)
    flash("Pembayaran disetujui." if approve else "Pembayaran ditolak.",
          "success" if approve else "info")
    return redirect(url_for("admin_payments.index"))


@bp.route("/<int:order_id>/approve", methods=["POST"])
@admin_required
def approve(order_id):
    return _review(order_id, "approve")


@bp.route("/<int:order_id>/reject", methods=["POST"])
@admin_required
def reject(order_id):
    return _review(order_id, "reject")