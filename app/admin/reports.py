import csv
import io
import logging
from datetime import datetime, timedelta, timezone

import click
from flask import (Blueprint, Response, abort, flash, redirect, render_template,
                   request, url_for)
from flask_login import current_user
from sqlalchemy import func, select

from ..extensions import db
from ..logging_setup import log_event
from ..models import Order, OrderItem, Payment, Product, User, utcnow
from .payments import _ctx, admin_required  # decorator & konteks log yang sama
from .report_forms import CancelOrderForm

bp = Blueprint("admin_reports", __name__, url_prefix="/admin/reports")

W = logging.WARNING
STATUSES = ("pending_payment", "waiting_verification", "paid", "cancelled")
CANCELLABLE = ("pending_payment", "waiting_verification")  # paid = refund, di luar cakupan
PER_PAGE = 25
CSV_MAX_ROWS = 10000

_qty = (select(func.coalesce(func.sum(OrderItem.quantity), 0))
        .where(OrderItem.order_id == Order.id).correlate(Order).scalar_subquery())


# ---------- filter & query ----------
def _parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _filters():
    status = request.args.get("status", "all")
    if status not in STATUSES:
        status = "all"
    df = _parse_date(request.args.get("date_from", "").strip())
    dt = _parse_date(request.args.get("date_to", "").strip())
    return dict(status=status, df=df, dt=dt,
                date_from=df.strftime("%Y-%m-%d") if df else "",
                date_to=dt.strftime("%Y-%m-%d") if dt else "")


def _query_args(f):
    return dict(status=f["status"], date_from=f["date_from"], date_to=f["date_to"])


def _date_filtered(q, f):
    if f["df"]:
        q = q.filter(Order.created_at >= f["df"])
    if f["dt"]:
        q = q.filter(Order.created_at < f["dt"] + timedelta(days=1))
    return q


def _rows_query(f):
    q = (db.session.query(Order, User, Payment.status.label("pay_status"), _qty.label("qty"))
         .join(User, Order.user_id == User.id)
         .outerjoin(Payment, Payment.order_id == Order.id))
    q = _date_filtered(q, f)
    if f["status"] != "all":
        q = q.filter(Order.status == f["status"])
    return q.order_by(Order.id.desc())


def _summary(f):
    q = db.session.query(Order.status, func.count(Order.id),
                         func.coalesce(func.sum(Order.total_idr), 0))
    q = _date_filtered(q, f).group_by(Order.status)
    by_status = {s: (0, 0) for s in STATUSES}
    for status, n, total in q.all():
        by_status[status] = (int(n), int(total))
    return dict(by_status=by_status,
                total=sum(n for n, _ in by_status.values()),
                omzet=by_status["paid"][1])


# ---------- laporan ----------
@bp.route("/")
@admin_required
def index():
    f = _filters()
    page = max(request.args.get("page", 1, type=int), 1)
    pag = _rows_query(f).paginate(page=page, per_page=PER_PAGE, error_out=False)
    return render_template("admin/report_list.html", pag=pag, f=f, args=_query_args(f),
                           summary=_summary(f), statuses=STATUSES)


def _csv_safe(v):
    """Cegah CSV/formula injection di Excel untuk teks bebas (username, email)."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


@bp.route("/export")
@admin_required
def export():
    f = _filters()
    rows = _rows_query(f).limit(CSV_MAX_ROWS).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["order_id", "created_at_utc", "username", "email", "total_idr",
                "total_qty", "order_status", "payment_status", "payment_method"])
    for o, u, pay_status, qty in rows:
        w.writerow([o.id, o.created_at.strftime("%Y-%m-%d %H:%M:%S"), _csv_safe(u.username),
                    _csv_safe(u.email), o.total_idr, int(qty), o.status, pay_status or "",
                    o.payment_method or ("manual" if pay_status else "")])
    log_event("admin.report_exported", row_count=len(rows), filter_status=f["status"],
              date_from=f["date_from"], date_to=f["date_to"], **_ctx())
    name = f"laporan-transaksi-{utcnow().strftime('%Y%m%d-%H%M')}.csv"
    return Response(buf.getvalue().encode("utf-8-sig"), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}"})


@bp.route("/orders/<int:order_id>")
@admin_required
def order_detail(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        abort(404)
    return render_template("admin/report_order.html", order=order, customer=order.user,
                           cancellable=order.status in CANCELLABLE, form=CancelOrderForm())


# ---------- pembatalan pesanan ----------
def cancel_order(order_id, allowed=CANCELLABLE, actor_id=None):
    """Batalkan pesanan & kembalikan stok dalam satu transaksi.
    Return (info, error). Dipakai route admin dan perintah CLI expire-orders."""
    order = db.session.query(Order).filter_by(id=order_id).with_for_update().first()
    if not order:
        db.session.rollback()
        return None, "not_found"
    if order.status not in allowed:
        status = order.status
        db.session.rollback()
        return None, f"status_{status}"

    pids = sorted({i.product_id for i in order.items})
    products = {p.id: p for p in Product.query.filter(Product.id.in_(pids))
                .order_by(Product.id).with_for_update().all()}
    restored = 0
    for it in order.items:
        p = products.get(it.product_id)
        if p:
            p.stock += it.quantity
            restored += it.quantity

    previous = order.status
    # Bukti bayar yang masih menunggu ikut ditutup agar tidak menggantung di antrean verifikasi
    if order.payment and order.payment.status == "waiting":
        order.payment.status = "rejected"
        order.payment.reviewed_by = actor_id
        order.payment.reviewed_at = utcnow()
    order.status = "cancelled"
    info = dict(order_id=order.id, customer_id=order.user_id, total_idr=order.total_idr,
                previous_status=previous, units_restored=restored)
    db.session.commit()
    return info, None


@bp.route("/orders/<int:order_id>/cancel", methods=["POST"])
@admin_required
def cancel(order_id):
    form = CancelOrderForm()
    if not form.validate_on_submit():
        flash("Input tidak valid.", "danger")
        return redirect(url_for("admin_reports.order_detail", order_id=order_id))
    info, err = cancel_order(order_id, actor_id=current_user.id)
    if err == "not_found":
        abort(404)
    if err:
        log_event("admin.order_cancel_invalid", level=W, order_id=order_id,
                  reason_code=err, **_ctx())
        flash("Pesanan ini tidak dapat dibatalkan pada statusnya sekarang.", "warning")
        return redirect(url_for("admin_reports.order_detail", order_id=order_id))
    log_event("admin.order_cancelled", reason=(form.reason.data or "")[:200], **info, **_ctx())
    flash("Pesanan dibatalkan dan stok dikembalikan.", "success")
    return redirect(url_for("admin_reports.order_detail", order_id=order_id))


# ---------- kedaluwarsa otomatis ----------
@bp.cli.command("expire-orders")
@click.option("--hours", default=24, show_default=True, help="Umur minimum pesanan belum bayar.")
@click.option("--dry-run", is_flag=True, help="Tampilkan saja, tanpa membatalkan.")
def expire_orders(hours, dry_run):
    """Batalkan pesanan pending_payment yang lewat batas waktu & kembalikan stok.
    Jalankan: flask admin_reports expire-orders --hours 24"""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    ids = [r[0] for r in db.session.query(Order.id).filter(
        Order.status == "pending_payment", Order.created_at < cutoff).all()]
    done = 0
    for oid in ids:
        if dry_run:
            click.echo(f"[dry-run] pesanan #{oid} akan dibatalkan")
            continue
        info, err = cancel_order(oid, allowed=("pending_payment",))
        if err:
            continue
        log_event("order.expired", level=logging.INFO, src_ip="cli", expire_after_hours=hours, **info)
        done += 1
    click.echo(f"{len(ids)} pesanan kedaluwarsa ditemukan, {done} dibatalkan.")