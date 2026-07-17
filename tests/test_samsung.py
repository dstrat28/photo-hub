from pathlib import Path

from photo_hub.samsung import SamsungConfig, SamsungFrame


class FakeArt:
    def __init__(self):
        self.upload_kwargs = None
        self.selected_content_id = None
        self.closed = False

    def get_artmode(self):
        raise AssertionError("delivery should not require Art Mode status")

    def upload(self, image_path, **kwargs):
        self.upload_kwargs = kwargs
        assert Path(image_path).name == "photo.jpg"
        return "MY_F0006"

    def select_image(self, content_id):
        self.selected_content_id = content_id

    def get_current(self):
        return self.selected_content_id

    def close(self):
        self.closed = True


def test_tv_upload_uses_samsung_matte(monkeypatch, tmp_path):
    fake_art = FakeArt()
    frame = SamsungFrame(SamsungConfig(host="192.168.1.50"))
    monkeypatch.setattr(frame, "_art", lambda: fake_art)
    image_path = tmp_path / "photo.jpg"
    image_path.write_bytes(b"jpeg")

    content_id = frame._upload_select_replace_inline(image_path, previous_content_id=None)

    assert content_id == "MY_F0006"
    assert fake_art.upload_kwargs == {
        "file_type": "JPEG",
        "matte": "shadowbox_polar",
        "portrait_matte": "shadowbox_polar",
    }
    assert fake_art.closed is True
