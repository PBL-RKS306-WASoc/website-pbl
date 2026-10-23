"""API internal untuk Active Response SOC (RPP 3.3): pembatasan akun lewat aplikasi,
bukan modifikasi langsung ke basis data. Hanya untuk host SOC (token + allowlist IP)."""
import hmac
import logging
from datetime import timedelta
from functools import wraps

from flask import Blueprint, current_app, jsonify, request

from ..extensions import csrf, db
from ..logging_setup import log_event
from ..models import User, utcnow

bp = Blueprint("soc_api", __name__, url_prefix="/internal/v1")
csrf.exempt(bp)  # dipanggil mesin (JSON + bearer token), bukan browser

W = logging.WARNING


def _src():
    return dict(src_ip=request.remote_addr, method=request.method, path=request.path)


def soc_auth(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        token = current_app.config.get("SOC_API_TOKEN", "")
        if not token:  # gagal tertutup: tanpa token terkonfigurasi, endpoint seolah tidak ada
            return jsonify(error="not_found"), 404
        ip_ok = request.remote_addr in current_app.config.get("SOC_API_ALLOWED_IPS", [])
        header = request.headers.get("Authorization", "")
        supplied = header[7:] if header.startswith("Bearer ") else ""
        token_ok = hmac.compare_digest(supplied.encode(), token.encode())
        if not (ip_ok and token_ok):
            log_event("soc_api.auth_failed", level=W, ip_allowed=ip_ok,
                      token_present=bool(supplied), **_src())
            return jsonify(error="unauthorized"), 401
        return fn(*a, **kw)
    return wrapper


def _reject(code, reason, status, **extra):
    log_event("soc_api.rejected", level=W, reason=reason, **extra, **_src())
    return jsonify(error=reason), status


def _payload():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _find_user(username):
    if not isinstance(username, str) or not (1 <= len(username) <= 50):
        return None, _reject("bad", "invalid_username", 400)
    u = User.query.filter_by(username=username).first()
    if not u:
        return None, _reject("nf", "user_not_found", 404, username=username[:50])
    return u, None


@bp.route("/accounts/restrict", methods=["POST"])
@soc_auth
def restrict():
    data = _payload()
    u, err = _find_user(data.get("username"))
    if err:
        return err
    if u.is_admin:  # cegah DoS terhadap admin lewat serangan yang memicu respons otomatis
        return _reject("prot", "protected_account", 403, username=u.username)

    cfg = current_app.config
    minutes = data.get("minutes", cfg["SOC_API_DEFAULT_MINUTES"])
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 1:
        return _reject("bad", "invalid_minutes", 400, username=u.username)
    minutes = min(minutes, cfg["SOC_API_MAX_MINUTES"])  # TTL wajib, ada batas atas

    reason = str(data.get("reason") or "soc_active_response")[:200]
    alert_id = str(data.get("alert_id") or "")[:64]
    until = utcnow() + timedelta(minutes=minutes)
    # jika sudah terkunci lebih lama, jangan dipersingkat
    if u.is_locked and u.locked_until > until.replace(tzinfo=None):
        until = u.locked_until
    u.locked_until = until
    u.lock_reason = reason
    db.session.commit()
    log_event("soc_api.account_restricted", level=W, target_user_id=u.id,
              target_username=u.username, minutes=minutes, reason=reason,
              alert_id=alert_id, locked_until=u.locked_until.isoformat(), **_src())
    return jsonify(status="restricted", username=u.username, minutes=minutes,
                   locked_until=u.locked_until.isoformat())


@bp.route("/accounts/release", methods=["POST"])
@soc_auth
def release():
    data = _payload()
    u, err = _find_user(data.get("username"))
    if err:
        return err
    u.locked_until = None
    if u.is_enabled:
        u.lock_reason = None
    db.session.commit()
    log_event("soc_api.account_released", target_user_id=u.id, target_username=u.username,
              alert_id=str(data.get("alert_id") or "")[:64], **_src())
    return jsonify(status="released", username=u.username)


@bp.route("/accounts/<username>", methods=["GET"])
@soc_auth
def status(username):
    u, err = _find_user(username)
    if err:
        return err
    return jsonify(username=u.username, role=u.role, enabled=bool(u.is_enabled),
                   locked=u.is_locked,
                   locked_until=u.locked_until.isoformat() if u.locked_until else None)