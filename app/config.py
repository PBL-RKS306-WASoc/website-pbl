import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class Config:
    # KeyError kalau belum diset: sengaja, supaya gagal cepat
    SECRET_KEY = os.environ["SECRET_KEY"]
    SQLALCHEMY_DATABASE_URI = os.environ["DATABASE_URL"]
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)

    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "uploads")
    LOG_FILE = os.environ.get("LOG_FILE", "logs/app.log")
    SOC_API_TOKEN = os.environ.get("SOC_API_TOKEN", "")
    SOC_API_ALLOWED_IPS = tuple(
        ip.strip()
        for ip in os.environ.get("SOC_API_ALLOWED_IPS", "127.0.0.1").split(",")
        if ip.strip()
    )
    SOC_API_DEFAULT_MINUTES = int(os.environ.get("SOC_API_DEFAULT_MINUTES", "30"))
    SOC_API_MAX_MINUTES = int(os.environ.get("SOC_API_MAX_MINUTES", "1440"))
    MIDTRANS_SERVER_KEY = os.environ.get("MIDTRANS_SERVER_KEY", "")
    MIDTRANS_CLIENT_KEY = os.environ.get("MIDTRANS_CLIENT_KEY", "")
    MIDTRANS_IS_PRODUCTION = os.environ.get("MIDTRANS_IS_PRODUCTION", "0") == "1"
