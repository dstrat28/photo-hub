from pathlib import Path

from photo_hub.store import PendingTVJob, Store


def test_processed_messages_are_idempotent(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    assert not store.has_processed("1")
    store.mark_processed("1", "accepted")
    assert store.has_processed("1")


def test_max_processed_uid_uses_numeric_order(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    assert store.max_processed_uid() is None
    store.mark_processed("9", "accepted")
    store.mark_processed("10", "accepted")
    assert store.max_processed_uid() == "10"


def test_pending_tv_replacement_returns_previous_path(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    assert store.replace_pending_tv(PendingTVJob("1", "a@example.com", first)) is None
    previous = store.replace_pending_tv(PendingTVJob("2", "b@example.com", second))
    assert previous == first
    pending = store.get_pending_tv()
    assert pending is not None
    assert pending.message_uid == "2"
    assert pending.image_path == second


def test_tv_content_id_roundtrip(tmp_path):
    store = Store(tmp_path / "state.sqlite3")
    assert store.get_current_tv_content_id() is None
    store.set_current_tv_content_id("MY_F0001")
    assert store.get_current_tv_content_id() == "MY_F0001"
    store.set_current_tv_content_id(None)
    assert store.get_current_tv_content_id() is None
