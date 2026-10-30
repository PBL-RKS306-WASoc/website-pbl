import hashlib

import pytest

from app import create_app, midtrans
from app.extensions import db
from app.models import Order, User


class TestConfig:
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_SECURE = False
    WTF_CSRF_ENABLED = False
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024
    UPLOAD_FOLDER = "uploads"
    LOG_FILE = "logs/test-midtrans.log"
    MIDTRANS_SERVER_KEY = "test-server-key"
    MIDTRANS_CLIENT_KEY = "test-client-key"
    MIDTRANS_IS_PRODUCTION = False
    SOC_API_TOKEN = ""
    SOC_API_ALLOWED_IPS = ("127.0.0.1",)
    SOC_API_DEFAULT_MINUTES = 30
    SOC_API_MAX_MINUTES = 1440


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr("app.setup_logging", lambda app: None)
    application = create_app(TestConfig)
    application.config.update(TESTING=True)
    with application.app_context():
        db.create_all()
        owner = User(username="owner", email="owner@example.test")
        owner.set_password("password123")
        other = User(username="other", email="other@example.test")
        other.set_password("password123")
        db.session.add_all([owner, other])
        db.session.flush()
        order = Order(
            user_id=owner.id,
            total_idr=125000,
            status="pending_payment",
            shipping_address="Test address",
            midtrans_order_id="BRN-1-1234567890",
        )
        db.session.add(order)
        db.session.commit()
        application.config["TEST_ORDER_ID"] = order.id
        application.config["TEST_OWNER_ID"] = owner.id
        application.config["TEST_OTHER_ID"] = other.id
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logged_in_client(client):
    response = client.post(
        "/auth/login",
        data={"username": "owner", "password": "password123"},
    )
    assert response.status_code == 302
    return client


def notification(app, transaction_status="settlement", gross_amount="125000.00", **extra):
    midtrans_order_id = "BRN-1-1234567890"
    status_code = "200"
    payload = {
        "order_id": midtrans_order_id,
        "status_code": status_code,
        "gross_amount": gross_amount,
        "transaction_status": transaction_status,
        "signature_key": hashlib.sha512(
            (
                midtrans_order_id
                + status_code
                + gross_amount
                + app.config["MIDTRANS_SERVER_KEY"]
            ).encode()
        ).hexdigest(),
    }
    payload.update(extra)
    return payload


def test_invalid_signature_is_rejected_and_logged(app, client, monkeypatch):
    events = []
    monkeypatch.setattr(
        midtrans,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )
    payload = notification(app)
    payload["signature_key"] = "invalid"

    response = client.post("/midtrans/notify", json=payload)

    assert response.status_code == 403
    assert events[0][0] == "midtrans.signature_invalid"
    assert events[0][1]["level"] == 30
    assert events[0][1]["src_ip"] == "127.0.0.1"


def test_amount_mismatch_is_rejected_without_changing_order(app, client, monkeypatch):
    events = []
    monkeypatch.setattr(
        midtrans,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )

    response = client.post(
        "/midtrans/notify",
        json=notification(app, gross_amount="125001.00"),
    )

    assert response.status_code == 400
    assert events[0][0] == "midtrans.amount_mismatch"
    assert events[0][1]["level"] == 30
    assert events[0][1]["expected"] == 125000
    assert events[0][1]["received"] == "125001.00"
    with app.app_context():
        order = db.session.get(Order, app.config["TEST_ORDER_ID"])
        assert order.status == "pending_payment"


def test_valid_settlement_and_duplicate_notifications_are_idempotent(app, client):
    response = client.post("/midtrans/notify", json=notification(app))
    assert response.status_code == 200

    response = client.post(
        "/midtrans/notify",
        json=notification(app, transaction_status="pending"),
    )
    assert response.status_code == 200

    with app.app_context():
        order = db.session.get(Order, app.config["TEST_ORDER_ID"])
        assert order.status == "paid"
        assert order.payment_method == "midtrans"

    with app.app_context():
        order = db.session.get(Order, app.config["TEST_ORDER_ID"])
        order.status = "cancelled"
        db.session.commit()
    response = client.post("/midtrans/notify", json=notification(app))
    assert response.status_code == 200
    with app.app_context():
        assert db.session.get(Order, app.config["TEST_ORDER_ID"]).status == "cancelled"


def test_other_customer_cannot_create_snap_payment(app, client, monkeypatch):
    called = []
    events = []
    monkeypatch.setattr(midtrans.requests, "post", lambda *args, **kwargs: called.append(True))
    monkeypatch.setattr(
        midtrans,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )
    response = client.post(
        "/auth/login",
        data={"username": "other", "password": "password123"},
    )
    assert response.status_code == 302

    response = client.post(f"/midtrans/pay/{app.config['TEST_ORDER_ID']}")

    assert response.status_code == 404
    assert not called
    assert events[0][0] == "orders.unauthorized_access"
    assert events[0][1]["src_ip"] == "127.0.0.1"


def test_snap_uses_database_total_and_unique_attempt_ids(app, logged_in_client, monkeypatch):
    calls = []

    class SnapResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"token": "test-snap-token"}

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return SnapResponse()

    monkeypatch.setattr(midtrans.requests, "post", fake_post)
    first = logged_in_client.post(f"/midtrans/pay/{app.config['TEST_ORDER_ID']}")
    second = logged_in_client.post(f"/midtrans/pay/{app.config['TEST_ORDER_ID']}")

    assert first.status_code == 200 and first.json == {"token": "test-snap-token"}
    assert second.status_code == 200
    assert calls[0][0] == "https://app.sandbox.midtrans.com/snap/v1/transactions"
    assert calls[0][1]["json"]["transaction_details"]["gross_amount"] == 125000
    assert calls[0][1]["timeout"] == 10
    with app.app_context():
        order = db.session.get(Order, app.config["TEST_ORDER_ID"])
        assert order.midtrans_order_id != "BRN-1-1234567890"
        assert order.payment_method == "midtrans"


def test_empty_server_key_disables_midtrans_endpoints_and_button(app, client):
    app.config["MIDTRANS_SERVER_KEY"] = ""

    assert client.post("/midtrans/pay/1").status_code == 404
    assert client.post("/midtrans/notify", json={}).status_code == 404
    client.post(
        "/auth/login",
        data={"username": "owner", "password": "password123"},
    )
    response = client.get("/orders/1")
    assert response.status_code == 200
    assert b"Bayar dengan Midtrans" not in response.data
