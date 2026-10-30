import hashlib
import hmac
import logging
import time
from decimal import Decimal, InvalidOperation
from functools import wraps

import requests
from flask import Blueprint, abort, current_app, jsonify, request
from flask_login import current_user, login_required

from ..extensions import csrf, db
from ..logging_setup import log_event
from ..models import Order

bp = Blueprint("midtrans", __name__, url_prefix="/midtrans")
W = logging.WARNING


def _enabled(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_app.config.get("MIDTRANS_SERVER_KEY"):
            abort(404)
        return view(*args, **kwargs)

    return wrapped


def _snap_url():
    if current_app.config.get("MIDTRANS_IS_PRODUCTION"):
        return "https://app.midtrans.com/snap/v1/transactions"
    return "https://app.sandbox.midtrans.com/snap/v1/transactions"


@bp.route("/pay/<int:order_id>", methods=["POST"])
@_enabled
@login_required
def pay(order_id):
    order = Order.query.filter_by(id=order_id).with_for_update().first()
    if not order:
        abort(404)
    if order.user_id != current_user.id:
        log_event(
            "orders.unauthorized_access",
            level=W,
            order_id=order_id,
            owner_id=order.user_id,
            action="midtrans_pay",
            user_id=current_user.id,
            username=current_user.username,
            src_ip=request.remote_addr,
            method=request.method,
            path=request.path,
        )
        abort(404)
    if order.status != "pending_payment" or (
        order.payment and order.payment.status == "waiting"
    ):
        return jsonify(error="Pembayaran tidak tersedia untuk pesanan ini."), 409

    timestamp = int(time.time())
    if order.midtrans_order_id:
        prefix = f"BRN-{order.id}-"
        previous_timestamp = order.midtrans_order_id[len(prefix):]
        if order.midtrans_order_id.startswith(prefix) and previous_timestamp.isdigit():
            timestamp = max(timestamp, int(previous_timestamp) + 1)
    midtrans_order_id = f"BRN-{order.id}-{timestamp}"

    order.midtrans_order_id = midtrans_order_id
    order.payment_method = "midtrans"
    db.session.commit()

    try:
        response = requests.post(
            _snap_url(),
            json={
                "transaction_details": {
                    "order_id": midtrans_order_id,
                    "gross_amount": order.total_idr,
                }
            },
            auth=(current_app.config["MIDTRANS_SERVER_KEY"], ""),
            timeout=10,
        )
        response.raise_for_status()
        token = response.json().get("token")
        if not isinstance(token, str) or not token:
            raise ValueError("Snap response missing token")
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        log_event(
            "midtrans.snap_error",
            level=logging.ERROR,
            order_id=order.id,
            src_ip=request.remote_addr,
        )
        return jsonify(error="Pembayaran Midtrans sedang tidak tersedia."), 502

    return jsonify(token=token)


@bp.route("/notify", methods=["POST"])
@csrf.exempt
@_enabled
def notify():
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    midtrans_order_id = data.get("order_id")
    status_code = data.get("status_code")
    gross_amount = data.get("gross_amount")
    signature = data.get("signature_key")

    if not all(isinstance(value, str) for value in (
        midtrans_order_id, status_code, gross_amount, signature
    )):
        log_event(
            "midtrans.signature_invalid",
            level=W,
            order_id=midtrans_order_id,
            src_ip=request.remote_addr,
        )
        return jsonify(error="Invalid signature."), 403

    expected_signature = hashlib.sha512(
        (
            midtrans_order_id
            + status_code
            + gross_amount
            + current_app.config["MIDTRANS_SERVER_KEY"]
        ).encode()
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        log_event(
            "midtrans.signature_invalid",
            level=W,
            order_id=midtrans_order_id,
            src_ip=request.remote_addr,
        )
        return jsonify(error="Invalid signature."), 403

    order = (
        Order.query.filter_by(midtrans_order_id=midtrans_order_id)
        .with_for_update()
        .first()
    )
    if not order:
        log_event(
            "midtrans.order_not_found",
            level=W,
            order_id=midtrans_order_id,
            src_ip=request.remote_addr,
        )
        return jsonify(error="Order not found."), 404

    try:
        received_amount = Decimal(gross_amount)
        valid_amount = received_amount.is_finite() and int(received_amount) == order.total_idr
    except (InvalidOperation, ValueError, OverflowError):
        valid_amount = False
    if not valid_amount:
        log_event(
            "midtrans.amount_mismatch",
            level=W,
            order_id=order.id,
            expected=order.total_idr,
            received=gross_amount[:64],
            src_ip=request.remote_addr,
        )
        return jsonify(error="Payment amount mismatch."), 400

    transaction_status = data.get("transaction_status")
    if order.status not in ("paid", "cancelled"):
        if transaction_status == "settlement" or (
            transaction_status == "capture" and data.get("fraud_status") == "accept"
        ):
            order.status = "paid"
            order.payment_method = "midtrans"
        elif transaction_status in ("deny", "cancel", "expire"):
            if order.status == "pending_payment":
                order.payment_method = "midtrans"
        elif transaction_status == "pending":
            pass
        db.session.commit()

    log_event(
        "midtrans.notification",
        transaction_status=transaction_status,
        order_id=order.id,
        src_ip=request.remote_addr,
    )
    return jsonify(status="ok")
