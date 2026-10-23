from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from flask_login import UserMixin
from sqlalchemy import true

from .extensions import db, login_manager

_ph = PasswordHasher()


def utcnow():
    return datetime.now(timezone.utc)


def _naive_utc(dt):
    """DB (MySQL) mengembalikan datetime naive UTC; objek baru bisa aware."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="customer")  # customer | admin
    full_name = db.Column(db.String(100))
    avatar_filename = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=utcnow)
    # Status akun: dinonaktifkan admin (permanen) atau dikunci sementara (admin/SOC, ada TTL)
    is_enabled = db.Column(db.Boolean, nullable=False, default=True, server_default=true())
    locked_until = db.Column(db.DateTime)
    lock_reason = db.Column(db.String(200))

    def set_password(self, password):
        self.password_hash = _ph.hash(password)

    def check_password(self, password):
        try:
            return _ph.verify(self.password_hash, password)
        except VerifyMismatchError:
            return False

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_locked(self):
        return bool(self.locked_until and _naive_utc(self.locked_until) > _naive_utc(utcnow()))

    @property
    def is_active(self):  # menimpa UserMixin.is_active, dibaca Flask-Login
        return bool(self.is_enabled) and not self.is_locked


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class Category(db.Model):
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)


class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    name = db.Column(db.String(150), nullable=False, index=True)
    description = db.Column(db.Text)
    price_idr = db.Column(db.Integer, nullable=False)  # rupiah, integer
    stock = db.Column(db.Integer, nullable=False, default=0)
    image_filename = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    category = db.relationship("Category", backref="products")


class Review(db.Model):
    __tablename__ = "reviews"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # validasi 1..5 di form
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)

    product = db.relationship("Product", backref="reviews")
    user = db.relationship("User")


class CartItem(db.Model):
    __tablename__ = "cart_items"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    __table_args__ = (db.UniqueConstraint("user_id", "product_id"),)

    product = db.relationship("Product")


class Order(db.Model):
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    total_idr = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="pending_payment")
    shipping_address = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    user = db.relationship("User")
    items = db.relationship("OrderItem", backref="order", cascade="all, delete-orphan")
    payment = db.relationship("Payment", backref="order", uselist=False)


class OrderItem(db.Model):
    __tablename__ = "order_items"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price_idr = db.Column(db.Integer, nullable=False)  # harga saat dibeli

    product = db.relationship("Product")


class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, unique=True)
    proof_filename = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="waiting")  # waiting|approved|rejected
    uploaded_at = db.Column(db.DateTime, default=utcnow)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    reviewed_at = db.Column(db.DateTime)