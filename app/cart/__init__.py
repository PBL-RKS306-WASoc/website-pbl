import logging

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..logging_setup import log_event
from ..models import CartItem, Product
from .forms import AddToCartForm, RemoveFromCartForm, UpdateCartForm

bp = Blueprint("cart", __name__, url_prefix="/cart")

W = logging.WARNING


def _ctx():
    return dict(
        user_id=current_user.id,
        username=current_user.username,
        src_ip=request.remote_addr,  # sudah benar di balik NGINX via ProxyFix
        path=request.path,
    )


@bp.app_template_filter("rupiah")
def rupiah(value):
    return "Rp " + f"{int(value):,}".replace(",", ".")


@bp.app_context_processor
def inject_cart_count():
    if current_user.is_authenticated:
        n = db.session.query(db.func.coalesce(db.func.sum(CartItem.quantity), 0)) \
            .filter(CartItem.user_id == current_user.id).scalar()
        return {"cart_count": int(n)}
    return {"cart_count": 0}


def _own_item_or_404(item_id, action):
    item = db.session.get(CartItem, item_id)
    if not item:
        abort(404)
    if item.user_id != current_user.id:  # IDOR: coba akses keranjang orang lain
        log_event("cart.unauthorized_access", level=W, item_id=item_id,
                  owner_id=item.user_id, action=action, **_ctx())
        abort(404)
    return item


@bp.route("/")
@login_required
def view():
    items = CartItem.query.filter_by(user_id=current_user.id).order_by(CartItem.id).all()
    rows, total = [], 0
    for it in items:
        p = it.product
        available = p.is_active and p.stock > 0
        qty = min(it.quantity, p.stock) if available else it.quantity
        subtotal = qty * p.price_idr if available else 0
        total += subtotal
        rows.append(dict(item=it, product=p, available=available, qty=qty, subtotal=subtotal))
    return render_template("cart/cart.html", rows=rows, total=total,
                           update_form=UpdateCartForm(), remove_form=RemoveFromCartForm())


@bp.route("/add", methods=["POST"])
@login_required
def add():
    form = AddToCartForm()
    if not form.validate_on_submit():
        log_event("cart.add_invalid", level=W, fields_invalid=list(form.errors.keys()), **_ctx())
        flash("Permintaan tidak valid.", "danger")
        return redirect(url_for("catalog.index"))

    product = db.session.get(Product, form.product_id.data)
    if not product or not product.is_active:
        log_event("cart.add_unknown_product", level=W, product_id=form.product_id.data, **_ctx())
        abort(404)

    server_price = product.price_idr
    client_price = form.price_idr.data
    if client_price is not None and client_price != server_price:
        # Sinyal manipulasi harga; harga klien diabaikan sepenuhnya
        log_event("cart.price_mismatch", level=W, product_id=product.id,
                  client_price=client_price, server_price=server_price,
                  quantity=form.quantity.data, **_ctx())

    item = CartItem.query.filter_by(user_id=current_user.id, product_id=product.id).first()
    new_qty = (item.quantity if item else 0) + form.quantity.data
    if new_qty > product.stock:
        new_qty = product.stock
        flash(f"Jumlah disesuaikan dengan stok tersedia ({product.stock}).", "warning")
    if new_qty < 1:
        flash("Stok barang habis.", "danger")
        return redirect(url_for("catalog.detail", product_id=product.id))

    if item:
        item.quantity = new_qty
    else:
        db.session.add(CartItem(user_id=current_user.id, product_id=product.id, quantity=new_qty))
    try:
        db.session.commit()
    except IntegrityError:  # race: dua request bersamaan
        db.session.rollback()
        flash("Gagal menambah ke keranjang, coba lagi.", "danger")
        return redirect(url_for("cart.view"))

    log_event("cart.add", product_id=product.id, quantity=form.quantity.data,
              cart_quantity=new_qty, server_price=server_price, **_ctx())
    flash(f"'{product.name}' ditambahkan ke keranjang.", "success")
    return redirect(url_for("cart.view"))


@bp.route("/update/<int:item_id>", methods=["POST"])
@login_required
def update(item_id):
    item = _own_item_or_404(item_id, "update")
    form = UpdateCartForm()
    if not form.validate_on_submit():
        log_event("cart.update_invalid", level=W, item_id=item_id, **_ctx())
        flash("Jumlah tidak valid.", "danger")
        return redirect(url_for("cart.view"))

    qty = form.quantity.data
    pid = item.product_id
    if qty == 0:
        db.session.delete(item)
        db.session.commit()
        log_event("cart.remove", product_id=pid, item_id=item_id, **_ctx())
        flash("Barang dihapus dari keranjang.", "info")
        return redirect(url_for("cart.view"))

    if qty > item.product.stock:
        qty = item.product.stock
        flash(f"Jumlah disesuaikan dengan stok ({qty}).", "warning")
    if qty < 1:
        db.session.delete(item)
        db.session.commit()
        flash("Stok habis, barang dihapus dari keranjang.", "danger")
        return redirect(url_for("cart.view"))

    item.quantity = qty
    db.session.commit()
    log_event("cart.update", product_id=pid, item_id=item_id, cart_quantity=qty, **_ctx())
    flash("Keranjang diperbarui.", "success")
    return redirect(url_for("cart.view"))


@bp.route("/remove/<int:item_id>", methods=["POST"])
@login_required
def remove(item_id):
    item = _own_item_or_404(item_id, "remove")
    if not RemoveFromCartForm().validate_on_submit():
        abort(400)
    pid = item.product_id
    db.session.delete(item)
    db.session.commit()
    log_event("cart.remove", product_id=pid, item_id=item_id, **_ctx())
    flash("Barang dihapus dari keranjang.", "info")
    return redirect(url_for("cart.view"))