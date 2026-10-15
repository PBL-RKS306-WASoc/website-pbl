from flask import Blueprint, abort, render_template, request
from ..extensions import db
from ..models import Category, Product

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
    return render_template("catalog/detail.html", product=product)