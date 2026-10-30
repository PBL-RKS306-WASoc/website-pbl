import logging
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from ..extensions import db
from ..logging_setup import log_event
from ..models import Category, Order, Product, User
from .forms import CategoryForm, ProductForm

bp = Blueprint("admin", __name__, url_prefix="/admin")


# Penjaga pintu khusus Admin (Otorisasi Peran)
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin:
            # Catat percobaan akses ilegal ke area admin (Syarat Poin 1 ATS)
            log_event(
                "access.denied",
                level=logging.WARNING,
                user_id=current_user.id,
                username=current_user.username,
                src_ip=request.remote_addr,
                method=request.method,
                path=request.path,
                reason="non_admin_access_attempt",
            )
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


# 1. DASHBOARD ADMIN DASAR (Syarat Poin 5 ATS)
@bp.route("/")
@admin_required
def dashboard():
    total_products = Product.query.count()
    total_users = User.query.count()
    total_orders = Order.query.count()
    paid_midtrans_orders = Order.query.filter_by(
        status="paid", payment_method="midtrans"
    ).count()
    paid_manual_orders = Order.query.filter(
        Order.status == "paid",
        or_(Order.payment_method == "manual", Order.payment_method.is_(None)),
    ).count()
    return render_template(
        "admin/dashboard.html",
        total_products=total_products,
        total_users=total_users,
        total_orders=total_orders,
        paid_manual_orders=paid_manual_orders,
        paid_midtrans_orders=paid_midtrans_orders,
    )


# 2. DAFTAR PRODUK & TAMBAH KATEGORI (Syarat Poin 3 ATS)
@bp.route("/products", methods=["GET", "POST"])
@admin_required
def products():
    cat_form = CategoryForm()
    if cat_form.validate_on_submit():
        existing = Category.query.filter_by(name=cat_form.name.data).first()
        if existing:
            flash("Kategori tersebut sudah ada.", "warning")
        else:
            cat = Category(name=cat_form.name.data)
            db.session.add(cat)
            db.session.commit()
            flash(f"Kategori '{cat.name}' berhasil ditambahkan.", "success")
        return redirect(url_for("admin.products"))

    all_products = Product.query.order_by(Product.id.desc()).all()
    all_categories = Category.query.order_by(Category.name).all()
    return render_template(
        "admin/products.html",
        products=all_products,
        categories=all_categories,
        cat_form=cat_form,
    )


# 3. TAMBAH PRODUK BARU (Create)
@bp.route("/products/new", methods=["GET", "POST"])
@admin_required
def product_create():
    categories = Category.query.order_by(Category.name).all()
    if not categories:
        flash("Buat minimal 1 kategori terlebih dahulu sebelum menambah barang!", "warning")
        return redirect(url_for("admin.products"))

    form = ProductForm()
    form.category_id.choices = [(c.id, c.name) for c in categories]

    if form.validate_on_submit():
        product = Product(
            name=form.name.data,
            category_id=form.category_id.data,
            price_idr=form.price_idr.data,
            stock=form.stock.data,
            description=form.description.data,
            is_active=form.is_active.data,
        )
        db.session.add(product)
        db.session.commit()

        log_event(
            "admin.product_created",
            user_id=current_user.id,
            username=current_user.username,
            product_id=product.id,
            product_name=product.name,
            src_ip=request.remote_addr,
            method=request.method,
            path=request.path,
        )
        flash(f"Barang '{product.name}' berhasil ditambahkan!", "success")
        return redirect(url_for("admin.products"))

    return render_template("admin/product_form.html", form=form, title="Tambah Barang Baru")


# 4. EDIT PRODUK (Update)
@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def product_edit(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        abort(404)

    categories = Category.query.order_by(Category.name).all()
    form = ProductForm(obj=product)
    form.category_id.choices = [(c.id, c.name) for c in categories]

    if form.validate_on_submit():
        product.name = form.name.data
        product.category_id = form.category_id.data
        product.price_idr = form.price_idr.data
        product.stock = form.stock.data
        product.description = form.description.data
        product.is_active = form.is_active.data
        db.session.commit()

        log_event(
            "admin.product_updated",
            user_id=current_user.id,
            username=current_user.username,
            product_id=product.id,
            src_ip=request.remote_addr,
            method=request.method,
            path=request.path,
        )
        flash(f"Barang '{product.name}' berhasil diperbarui!", "success")
        return redirect(url_for("admin.products"))

    return render_template("admin/product_form.html", form=form, title="Edit Barang")


# 5. HAPUS PRODUK (Delete)
@bp.route("/products/<int:product_id>/delete", methods=["POST"])
@admin_required
def product_delete(product_id):
    product = db.session.get(Product, product_id)
    if not product:
        abort(404)

    product_name = product.name
    db.session.delete(product)
    db.session.commit()

    log_event(
        "admin.product_deleted",
        user_id=current_user.id,
        username=current_user.username,
        product_id=product_id,
        product_name=product_name,
        src_ip=request.remote_addr,
        method=request.method,
        path=request.path,
    )
    flash(f"Barang '{product_name}' telah dihapus.", "info")
    return redirect(url_for("admin.products"))