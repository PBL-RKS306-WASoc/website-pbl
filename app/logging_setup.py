import json
import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")
LOGGER_NAME = "shop.security"


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, WIB).isoformat(timespec="seconds"),
            "level": record.levelname,
            "event": getattr(record, "event", record.getMessage()),
        }
        entry.update(getattr(record, "fields", {}))
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(app):
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:  # cegah handler ganda saat reload
        return
    log_file = app.config["LOG_FILE"]
    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
    handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = False


def log_event(event, level=logging.INFO, **fields):
    """Contoh: log_event("auth.login_failed", level=logging.WARNING,
    username=u, src_ip=request.remote_addr, path=request.path)"""
    logging.getLogger(LOGGER_NAME).log(level, event, extra={"event": event, "fields": fields})