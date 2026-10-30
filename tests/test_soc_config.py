import os
from importlib import reload

os.environ.setdefault("SECRET_KEY", "soc-config-test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from app import config


def test_soc_settings_are_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("SOC_API_TOKEN", "soc-config-test-token")
    monkeypatch.setenv("SOC_API_ALLOWED_IPS", "127.0.0.1, 10.0.0.1")
    monkeypatch.setenv("SOC_API_DEFAULT_MINUTES", "45")
    monkeypatch.setenv("SOC_API_MAX_MINUTES", "1200")

    reload(config)

    assert config.Config.SOC_API_TOKEN == "soc-config-test-token"
    assert config.Config.SOC_API_ALLOWED_IPS == ("127.0.0.1", "10.0.0.1")
    assert config.Config.SOC_API_DEFAULT_MINUTES == 45
    assert config.Config.SOC_API_MAX_MINUTES == 1200
