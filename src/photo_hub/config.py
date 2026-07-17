"""Configuration loading for Photo Hub."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List


class ConfigError(RuntimeError):
    """Configuration is missing or invalid."""


@dataclass(frozen=True)
class GmailConfig:
    email: str
    app_password: str
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465


@dataclass(frozen=True)
class AuraConfig:
    frame_email: str


@dataclass(frozen=True)
class TVConfig:
    host: str
    enabled: bool = True
    client_name: str = "Frame TV"
    timeout_seconds: int = 30


@dataclass(frozen=True)
class PathsConfig:
    state_dir: Path


@dataclass(frozen=True)
class AppConfig:
    gmail: GmailConfig
    aura: AuraConfig
    tv: TVConfig
    paths: PathsConfig
    allowed_senders: List[str]
    poll_interval_seconds: int = 60
    max_attachment_bytes: int = 25_000_000


def _require_mapping(raw: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError("Missing object config key: {}".format(key))
    return value


def _require_str(raw: Dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("Missing string config key: {}".format(key))
    value = value.strip()
    lowered = value.lower()
    if lowered.startswith("replace-with") or lowered.startswith("your-"):
        raise ConfigError("Config key {} still contains a placeholder value".format(key))
    return value


def load_config(path: Path) -> AppConfig:
    try:
        raw = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError("Could not read config file: {}".format(path)) from exc

    gmail_raw = _require_mapping(raw, "gmail")
    aura_raw = _require_mapping(raw, "aura")
    tv_raw = _require_mapping(raw, "tv")
    paths_raw = _require_mapping(raw, "paths")

    allowed = raw.get("allowed_senders")
    if not isinstance(allowed, list) or not allowed:
        raise ConfigError("allowed_senders must be a non-empty list")
    allowed_senders = []
    for sender in allowed:
        if not isinstance(sender, str) or "@" not in sender:
            raise ConfigError("allowed_senders contains an invalid email address")
        allowed_senders.append(sender.strip().lower())

    state_dir = Path(_require_str(paths_raw, "state_dir")).expanduser()
    return AppConfig(
        gmail=GmailConfig(
            email=_require_str(gmail_raw, "email"),
            app_password=_require_str(gmail_raw, "app_password"),
            imap_host=str(gmail_raw.get("imap_host", "imap.gmail.com")),
            imap_port=int(gmail_raw.get("imap_port", 993)),
            smtp_host=str(gmail_raw.get("smtp_host", "smtp.gmail.com")),
            smtp_port=int(gmail_raw.get("smtp_port", 465)),
        ),
        aura=AuraConfig(frame_email=_require_str(aura_raw, "frame_email")),
        tv=TVConfig(
            host=_require_str(tv_raw, "host"),
            enabled=bool(tv_raw.get("enabled", True)),
            client_name=str(tv_raw.get("client_name", "Frame TV")),
            timeout_seconds=int(tv_raw.get("timeout_seconds", 30)),
        ),
        paths=PathsConfig(state_dir=state_dir),
        allowed_senders=allowed_senders,
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 60)),
        max_attachment_bytes=int(raw.get("max_attachment_bytes", 25_000_000)),
    )
