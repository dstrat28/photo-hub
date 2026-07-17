import json
import sys
from types import ModuleType

import pytest

from photo_hub.tv_probe import (
    ART_PORT,
    ProbeError,
    ProbeState,
    build_parser,
    connect_art,
    confirm_current_image,
    extract_content_id,
    interpret_art_mode,
    load_state,
    require_active_art_mode,
    save_state,
)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("on", True),
        ("off", False),
        ({"value": "on"}, True),
        ({"artmode": "off"}, False),
        ('{"value":"on"}', True),
        ("unexpected", None),
    ],
)
def test_interpret_art_mode(response, expected):
    assert interpret_art_mode(response) is expected


def test_refuses_upload_when_tv_is_not_known_to_be_in_art_mode():
    with pytest.raises(ProbeError, match="not in Art Mode"):
        require_active_art_mode("off")
    with pytest.raises(ProbeError, match="could not be interpreted"):
        require_active_art_mode({"unknown": "state"})


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"content_id": "MY-F0001"}, "MY-F0001"),
        ({"data": {"contentId": "MY-F0002"}}, "MY-F0002"),
        ('{"content_id": "MY-F0003"}', "MY-F0003"),
        ("created MY-F0004", "MY-F0004"),
        ({"content_id": "SAM-F0126"}, "SAM-F0126"),
        ({"content_id": "37"}, "37"),
        ("37", "37"),
    ],
)
def test_extract_content_id(response, expected):
    assert extract_content_id(response) == expected


def test_state_deletes_only_ids_it_recorded(tmp_path):
    state_path = tmp_path / "probe-state.json"
    state = ProbeState()
    state.mark_uploaded("MY-F0001")
    state.mark_displayed("MY-F0001")
    save_state(state_path, state)

    restored = load_state(state_path)
    with pytest.raises(ProbeError, match="not recorded"):
        restored.mark_deleted("MY-USER-PHOTO")
    restored.mark_deleted("MY-F0001")
    save_state(state_path, restored)

    raw = json.loads(state_path.read_text())
    assert raw["owned_content_ids"] == []
    assert raw["deleted_content_ids"] == ["MY-F0001"]
    assert raw["current_content_id"] is None


def test_confirms_selected_artwork_is_current():
    class Art:
        def get_current(self):
            return {"content_id": "MY-F0002"}

    confirm_current_image(Art(), "MY-F0002")
    with pytest.raises(ProbeError, match="did not confirm"):
        confirm_current_image(Art(), "MY-F0003")


@pytest.mark.parametrize("command", ["preflight", "status", "upload", "replace"])
def test_parser_accepts_public_probe_commands(command):
    args = build_parser().parse_args(["--host", "192.168.1.50", command])
    assert args.command == command


def test_parser_accepts_confirmed_cleanup():
    args = build_parser().parse_args(
        ["--host", "192.168.1.50", "cleanup", "--confirm"]
    )
    assert args.command == "cleanup"
    assert args.confirm is True


def test_connect_art_uses_the_direct_local_art_channel(monkeypatch):
    captured = {}

    class FakeArt:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    package = ModuleType("samsungtvws")
    package.__path__ = []
    art_module = ModuleType("samsungtvws.art")
    art_module.SamsungTVArt = FakeArt
    package.art = art_module
    monkeypatch.setitem(sys.modules, "samsungtvws", package)
    monkeypatch.setitem(sys.modules, "samsungtvws.art", art_module)
    args = build_parser().parse_args(["--host", "192.168.1.50", "status"])

    assert isinstance(connect_art(args), FakeArt)
    assert captured == {
        "host": "192.168.1.50",
        "port": ART_PORT,
        "timeout": 10,
        "name": "Frame TV",
    }


def test_status_parser_has_one_direct_connection_path():
    args = build_parser().parse_args(["--host", "192.168.1.50", "status"])
    assert set(vars(args)) == {"host", "state_dir", "timeout", "command"}
