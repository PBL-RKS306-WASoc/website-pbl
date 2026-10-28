from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..logging_setup import log_event
from ..models import Category, Order, OrderItem, Product, Review
from .forms import ReviewForm

bp = Blueprint("catalog", __name__)


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    category_id = request.args.get("category_id", type=int)

    query = Product.query.filter_by(is_active=True)

    # Filter pencarian nama barang
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))
    # Filter kategori
    if category_id:
        query = query.filter_by(category_id=category_id)

    products = query.order_by(Product.id.desc()).all()
    categories = Category.query.order_by(Category.name).all()

    return render_template(
        "catalog/index.html",
        products=products,
        categories=categories,
        q=q,
        selected_category=category_id,
    )


@bp.route("/products/<int:product_id>")
def detail(product_id):
    product = db.session.get(Product, product_id)
    if not product or not product.is_active:
        abort(404)

    reviews = (Review.query.filter_by(product_id=product.id)
               .order_by(Review.created_at.desc(), Review.id.desc()).all())
    average_rating = db.session.query(func.avg(Review.rating)).filter_by(
        product_id=product.id
    ).scalar()
    user_review = None
    can_review = False
    if current_user.is_authenticated and not current_user.is_admin:
        user_review = Review.query.filter_by(
            product_id=product.id,
            user_id=current_user.id,
        ).first()
        has_paid_purchase = (
            db.session.query(OrderItem.id)
            .join(Order, Order.id == OrderItem.order_id)
            .filter(
                Order.user_id == current_user.id,
                Order.status == "paid",
                OrderItem.product_id == product.id,
            )
            .first()
        )
        can_review = bool(has_paid_purchase and not user_review)

    return render_template(
        "catalog/detail.html",
        product=product,
        reviews=reviews,
        average_rating=average_rating,
        can_review=can_review,
        user_review=user_review,
        review_form=ReviewForm(),
    )


@bp.route("/products/<int:product_id>/reviews", methods=["POST"])
@login_required
def create_review(product_id):
    product = db.session.get(Product, product_id)
    if not product or not product.is_active:
        abort(404)
    if current_user.is_admin:
        abort(403)

    form = ReviewForm()
    if not form.validate_on_submit():
        flash("Rating harus 1-5 dan ulasan maksimal 1000 karakter.", "danger")
        return redirect(url_for("catalog.detail", product_id=product.id))

    has_paid_purchase = (
        db.session.query(OrderItem.id)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(
            Order.user_id == current_user.id,
            Order.status == "paid",
            OrderItem.product_id == product.id,
        )
        .first()
    )
    if not has_paid_purchase:
        flash("Ulasan hanya dapat diberikan untuk produk dari pesanan yang telah dibayar.", "warning")
        return redirect(url_for("catalog.detail", product_id=product.id))

    review = Review(
        product_id=product.id,
        user_id=current_user.id,
        rating=form.rating.data,
        comment=(form.comment.data or "").strip() or None,
    )
    db.session.add(review)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing_review = Review.query.filter_by(
            product_id=product.id,
            user_id=current_user.id,
        ).first()
        if existing_review:
            flash("Anda sudah mengulas produk ini.", "warning")
            return redirect(url_for("catalog.detail", product_id=product.id))
        raise

    log_event(
        "catalog.review_created",
        review_id=review.id,
        product_id=product.id,
        user_id=current_user.id,
        username=current_user.username,
        rating=review.rating,
        src_ip=request.remote_addr,
        method=request.method,
        path=request.path,
    )
    flash("Ulasan berhasil dikirim.", "success")
    return redirect(url_for("catalog.detail", product_id=product.id) + "#reviews")