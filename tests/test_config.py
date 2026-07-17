import json

import pytest

from photo_hub.config import ConfigError, load_config


def valid_config(tmp_path):
    return {
        "gmail": {
            "email": "photo-hub@example.com",
            "app_password": "app-password",
        },
        "allowed_senders": ["you@example.com"],
        "aura": {"frame_email": "frame@example.com"},
        "tv": {"host": "192.168.1.50"},
        "paths": {"state_dir": str(tmp_path / "state")},
    }


def write_config(tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_config_accepts_valid_config(tmp_path):
    config = load_config(write_config(tmp_path, valid_config(tmp_path)))
    assert config.tv.host == "192.168.1.50"
    assert config.allowed_senders == ["you@example.com"]


def test_load_config_rejects_placeholder_values(tmp_path):
    data = valid_config(tmp_path)
    data["gmail"]["app_password"] = "replace-with-gmail-app-password"
    with pytest.raises(ConfigError, match="placeholder"):
        load_config(write_config(tmp_path, data))
