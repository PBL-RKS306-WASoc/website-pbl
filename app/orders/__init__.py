import hashlib
import logging
import os
import uuid
from functools import wraps

import magic
from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, send_from_directory, session, url_for)
from flask_login import current_user
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import secure_filename

from ..extensions import db
from ..logging_setup import log_event
from ..models import CartItem, Order, OrderItem, Payment, Product, utcnow
from .forms import CheckoutForm, PaymentProofForm

bp = Blueprint("orders", __name__)

W = logging.WARNING
ALLOWED_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
MIME_EXT = {"image/jpeg": "jpg", "image/png": "png"}


# ---------- helper ----------
def _sid():
    # id sesi Flask-Login (hash), dipotong; cukup untuk korelasi di SIEM
    return (session.get("_id") or "")[:16]


def _ctx():
    return dict(user_id=current_user.id, username=current_user.username,
                src_ip=request.remote_addr, method=request.method,
                path=request.path, session_id=_sid())


def auth_required(event):
    """login_required + catat percobaan tanpa sesi valid (metrik dashboard)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not current_user.is_authenticated:
                log_event(event, level=W, src_ip=request.remote_addr,
                          method=request.method, path=request.path, session_id=_sid())
                return current_app.login_manager.unauthorized()
            return fn(*a, **kw)
        return wrapper
    return deco


def _proof_dir():
    base = current_app.config["UPLOAD_FOLDER"]
    if not os.path.isabs(base):
        base = os.path.join(os.path.dirname(current_app.root_path), base)
    return os.path.join(base, "payment_proofs")


def _order_or_404(order_id, action, allow_admin=False):
    order = db.session.get(Order, order_id)
    if not order:
        abort(404)
    if order.user_id != current_user.id and not (allow_admin and current_user.is_admin):
        log_event("orders.unauthorized_access", level=W, order_id=order_id,
                  owner_id=order.user_id, action=action, **_ctx())
        abort(404)
    return order


def _can_upload(order):
    return order.status == "pending_payment" and (
        order.payment is None or order.payment.status == "rejected")


def _summarize(items):
    rows, total = [], 0
    for it in items:
        p = it.product
        subtotal = it.quantity * p.price_idr
        total += subtotal
        rows.append(dict(item=it, product=p, qty=it.quantity, subtotal=subtotal,
                         available=p.is_active and p.stock >= it.quantity))
    return rows, total


# ---------- checkout ----------
@bp.route("/checkout", methods=["GET", "POST"])
@auth_required("checkout.unauthenticated_access")
def checkout():
    items = CartItem.query.filter_by(user_id=current_user.id).order_by(CartItem.id).all()
    if not items:
        flash("Keranjang masih kosong.", "warning")
        return redirect(url_for("cart.view"))

    form = CheckoutForm()
    if request.method == "GET" or not form.validate_on_submit():
        if request.method == "POST":
            log_event("checkout.form_invalid",
                      level=W if "total_idr" in form.errors else logging.INFO,
                      fields_invalid=list(form.errors.keys()), **_ctx())
        rows, total = _summarize(items)
        return render_template("orders/checkout.html", form=form, rows=rows, total=total)

    # Kunci baris produk (urut id agar tidak deadlock) lalu validasi di dalam transaksi
    ids = sorted({i.product_id for i in items})
    try:
        products = {p.id: p for p in Product.query.filter(Product.id.in_(ids))
                    .order_by(Product.id).with_for_update().all()}

        # 1) Validasi harga kiriman klien vs harga server
        mismatch = False
        server_total = 0
        for it in items:
            p = products.get(it.product_id)
            client_price = request.form.get(f"price_{it.product_id}", type=int)
            server_price = p.price_idr if p else None
            if p is None or client_price != server_price:
                mismatch = True
                log_event("checkout.price_mismatch", level=W, product_id=it.product_id,
                          client_price=client_price, server_price=server_price,
                          quantity=it.quantity, **_ctx())
            if p:
                server_total += it.quantity * p.price_idr
        if form.total_idr.data != server_total:
            mismatch = True
            log_event("checkout.total_mismatch", level=W,
                      client_total=form.total_idr.data, server_total=server_total, **_ctx())
        if mismatch:
            db.session.rollback()
            flash("Harga tidak sesuai dengan data toko. Silakan muat ulang checkout.", "danger")
            return redirect(url_for("cart.view"))

        # 2) Validasi ketersediaan
        for it in items:
            p = products[it.product_id]
            if not p.is_active or p.stock < it.quantity:
                db.session.rollback()
                log_event("checkout.stock_insufficient", product_id=p.id,
                          quantity=it.quantity, stock=p.stock, **_ctx())
                flash(f"Stok '{p.name}' tidak mencukupi.", "danger")
                return redirect(url_for("cart.view"))

        # 3) Buat pesanan: total dari harga server, simpan harga saat dibeli
        order = Order(user_id=current_user.id, total_idr=server_total,
                      shipping_address=form.shipping_address.data.strip(),
                      status="pending_payment")
        for it in items:
            p = products[it.product_id]
            order.items.append(OrderItem(product_id=p.id, quantity=it.quantity,
                                         unit_price_idr=p.price_idr))
            p.stock -= it.quantity
            db.session.delete(it)
        db.session.add(order)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        log_event("checkout.error", level=logging.ERROR, **_ctx())
        flash("Checkout gagal, coba lagi.", "danger")
        return redirect(url_for("cart.view"))

    log_event("checkout.success", order_id=order.id, total_idr=server_total,
              item_count=len(order.items), **_ctx())
    flash("Pesanan dibuat. Silakan unggah bukti pembayaran.", "success")
    return redirect(url_for("orders.detail", order_id=order.id))


# ---------- riwayat & detail ----------
@bp.route("/orders/")
@auth_required("orders.unauthenticated_access")
def history():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.id.desc()).all()
    return render_template("orders/list.html", orders=orders)


@bp.route("/orders/<int:order_id>")
@auth_required("orders.unauthenticated_access")
def detail(order_id):
    order = _order_or_404(order_id, "view")
    return render_template("orders/detail.html", order=order,
                           form=PaymentProofForm(), can_upload=_can_upload(order),
                           midtrans_enabled=bool(current_app.config.get("MIDTRANS_SERVER_KEY")
                                                 and current_app.config.get("MIDTRANS_CLIENT_KEY")),
                           midtrans_client_key=current_app.config.get("MIDTRANS_CLIENT_KEY", ""),
                           snap_js_url=("https://app.midtrans.com/snap/snap.js"
                                        if current_app.config.get("MIDTRANS_IS_PRODUCTION")
                                        else "https://app.sandbox.midtrans.com/snap/snap.js"))


# ---------- upload bukti bayar ----------
def _check_proof(orig_ext, data):
    """Return (ok, reason, detected_mime)."""
    if not data:
        return False, "empty_file", None
    if orig_ext not in ALLOWED_EXT:
        return False, "bad_extension", None
    detected = magic.from_buffer(data[:2048], mime=True)
    if detected not in MIME_EXT:
        return False, "bad_magic", detected
    if ALLOWED_EXT[orig_ext] != detected:
        return False, "ext_mime_mismatch", detected
    return True, None, detected


@bp.route("/orders/<int:order_id>/pay", methods=["POST"])
@auth_required("orders.unauthenticated_access")
def pay(order_id):
    order = _order_or_404(order_id, "upload_proof")
    if not _can_upload(order):
        flash("Bukti bayar tidak dapat diunggah untuk pesanan ini.", "warning")
        return redirect(url_for("orders.detail", order_id=order.id))

    form = PaymentProofForm()
    if not form.validate_on_submit():
        flash("Pilih berkas bukti pembayaran.", "danger")
        return redirect(url_for("orders.detail", order_id=order.id))

    f = form.proof.data
    orig = secure_filename(f.filename or "")[:100]
    data = f.read()
    ok, reason, detected = _check_proof(os.path.splitext(orig)[1].lower(), data)
    if not ok:
        log_event("upload.rejected", level=W, order_id=order.id, reason=reason,
                  original_name=orig, detected_mime=detected, size=len(data), **_ctx())
        flash("Berkas ditolak. Unggah gambar JPG atau PNG yang valid.", "danger")
        return redirect(url_for("orders.detail", order_id=order.id))

    # Nama acak + ekstensi dari hasil deteksi, bukan dari input pengguna
    stored = f"{uuid.uuid4().hex}.{MIME_EXT[detected]}"
    folder = _proof_dir()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, stored)
    with open(path, "wb") as fh:
        fh.write(data)
    try:
        os.chmod(path, 0o640)  # tanpa hak eksekusi (diabaikan di Windows)
    except OSError:
        pass

    if order.payment:
        pay_obj = order.payment
        pay_obj.proof_filename, pay_obj.status = stored, "waiting"
        pay_obj.uploaded_at, pay_obj.reviewed_by, pay_obj.reviewed_at = utcnow(), None, None
    else:
        db.session.add(Payment(order_id=order.id, proof_filename=stored))
    order.status = "waiting_verification"
    order.payment_method = "manual"
    db.session.commit()

    log_event("upload.proof_saved", order_id=order.id, stored_name=stored,
              original_name=orig, detected_mime=detected, size=len(data),
              sha256=hashlib.sha256(data).hexdigest(), **_ctx())
    flash("Bukti pembayaran terkirim, menunggu verifikasi admin.", "success")
    return redirect(url_for("orders.detail", order_id=order.id))


@bp.route("/orders/<int:order_id>/proof")
@auth_required("orders.unauthenticated_access")
def proof(order_id):
    order = _order_or_404(order_id, "view_proof", allow_admin=True)
    if not order.payment:
        abort(404)
    name = order.payment.proof_filename
    mime = "image/png" if name.endswith(".png") else "image/jpeg"
    resp = send_from_directory(_proof_dir(), name, mimetype=mime)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp