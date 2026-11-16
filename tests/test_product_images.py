from io import BytesIO

from PIL import Image

import app as app_package
from app import create_app
from app.extensions import db
from app.models import Category, Product, User


class TestConfig:
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    TESTING = True
    UPLOAD_FOLDER = "uploads"
    LOG_FILE = "logs/test.log"


def _image_upload():
    image = BytesIO()
    Image.new("RGB", (4, 4), color="blue").save(image, format="PNG")
    image.seek(0)
    return image


def _setup_app(monkeypatch, tmp_path):
    monkeypatch.setattr(app_package, "setup_logging", lambda app: None)
    app = create_app(TestConfig)
    app.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    with app.app_context():
        db.create_all()
        admin = User(
            username="admin",
            email="admin@example.test",
            password_hash="test-hash",
            role="admin",
        )
        category = Category(name="Pakaian")
        db.session.add_all([admin, category])
        db.session.commit()
        admin_id = admin.id
        category_id = category.id

    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(admin_id)
        session["_fresh"] = True
    return app, client, category_id


def test_admin_product_upload_shows_image_and_caption(monkeypatch, tmp_path):
    app, client, category_id = _setup_app(monkeypatch, tmp_path)
    response = client.post(
        "/admin/products/new",
        data={
            "name": "Kemeja Biru",
            "category_id": str(category_id),
            "price_idr": "150000",
            "stock": "3",
            "description": "Katun",
            "is_active": "y",
            "image": (_image_upload(), "kemeja.png"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 302
    with app.app_context():
        product = Product.query.one()
        image_filename = product.image_filename
        product_id = product.id
        assert image_filename.endswith(".png")

    image_response = client.get(f"/products/{product_id}/image")
    assert image_response.status_code == 200
    assert image_response.mimetype == "image/png"
    assert b"Kemeja Biru" in client.get("/").data
    assert b"Kemeja Biru" in client.get(f"/products/{product_id}").data


def test_admin_cannot_create_product_without_a_valid_photo(monkeypatch, tmp_path):
    app, client, category_id = _setup_app(monkeypatch, tmp_path)
    response = client.post(
        "/admin/products/new",
        data={
            "name": "Kemeja",
            "category_id": str(category_id),
            "price_idr": "150000",
            "stock": "3",
            "is_active": "y",
        },
    )

    assert response.status_code == 200
    assert "Foto produk wajib diunggah." in response.get_data(as_text=True)
    with app.app_context():
        assert Product.query.count() == 0


def test_image_extension_must_match_image_content(monkeypatch, tmp_path):
    _, client, category_id = _setup_app(monkeypatch, tmp_path)
    response = client.post(
        "/admin/products/new",
        data={
            "name": "Kemeja",
            "category_id": str(category_id),
            "price_idr": "150000",
            "stock": "3",
            "image": (_image_upload(), "kemeja.jpg"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert "Isi berkas tidak sesuai" in response.get_data(as_text=True)


def test_legacy_product_requires_photo_until_one_is_uploaded(monkeypatch, tmp_path):
    app, client, category_id = _setup_app(monkeypatch, tmp_path)
    with app.app_context():
        product = Product(
            name="Produk Lama",
            category_id=category_id,
            price_idr=150000,
            stock=3,
            is_active=True,
        )
        db.session.add(product)
        db.session.commit()
        product_id = product.id

    form_data = {
        "name": "Produk Lama",
        "category_id": str(category_id),
        "price_idr": "150000",
        "stock": "3",
        "is_active": "y",
    }
    response = client.post(f"/admin/products/{product_id}/edit", data=form_data)
    assert response.status_code == 200
    assert "Foto produk wajib diunggah." in response.get_data(as_text=True)

    response = client.post(
        f"/admin/products/{product_id}/edit",
        data={**form_data, "image": (_image_upload(), "produk.png")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with app.app_context():
        product = db.session.get(Product, product_id)
        assert product.image_filename.endswith(".png")
