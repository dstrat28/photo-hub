"""Samsung Frame Art delivery over the direct local Art channel."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import multiprocessing
from pathlib import Path
import queue
import signal
from typing import Optional

from .tv_probe import extract_content_id, interpret_art_mode


class SamsungError(RuntimeError):
    """Samsung TV operation failed."""


@dataclass(frozen=True)
class SamsungConfig:
    host: str
    client_name: str = "Frame TV"
    timeout_seconds: int = 30


class SamsungFrame:
    def __init__(self, config: SamsungConfig):
        self.config = config

    def _art(self):
        try:
            from samsungtvws.art import SamsungTVArt
        except ImportError as exc:
            raise SamsungError("samsungtvws is not installed.") from exc
        return SamsungTVArt(
            host=self.config.host,
            port=8001,
            timeout=self.config.timeout_seconds,
            name=self.config.client_name,
        )

    @contextmanager
    def _operation_timeout(self):
        def timeout_handler(signum, frame):
            raise TimeoutError("Samsung TV operation timed out.")

        previous = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(self.config.timeout_seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)

    def is_art_mode(self) -> bool:
        art = self._art()
        try:
            try:
                with self._operation_timeout():
                    mode = interpret_art_mode(art.get_artmode())
            except Exception as exc:
                raise SamsungError("Could not read TV Art Mode status.") from exc
            if mode is None:
                raise SamsungError("Could not interpret Art Mode status.")
            return mode
        finally:
            close = getattr(art, "close", None)
            if close:
                close()

    def upload_select_replace(self, image_path: Path, previous_content_id: Optional[str]) -> str:
        ctx = multiprocessing.get_context("spawn")
        result_queue = ctx.Queue()
        process = ctx.Process(
            target=_upload_select_replace_worker,
            args=(self.config, str(image_path), previous_content_id, result_queue),
        )
        process.start()
        process.join(self.config.timeout_seconds + 5)
        if process.is_alive():
            process.terminate()
            process.join(5)
            raise SamsungError("Samsung TV operation timed out.")
        try:
            status, payload = result_queue.get_nowait()
        except queue.Empty as exc:
            raise SamsungError("Samsung TV operation did not return a result.") from exc
        if status == "ok":
            return str(payload)
        raise SamsungError(str(payload))

    def _upload_select_replace_inline(
        self, image_path: Path, previous_content_id: Optional[str]
    ) -> str:
        art = self._art()
        try:
            try:
                with self._operation_timeout():
                    content_id = art.upload(
                        str(image_path),
                        file_type="JPEG",
                        matte="shadowbox_polar",
                        portrait_matte="shadowbox_polar",
                    )
                    content_id = extract_content_id(content_id)
                    art.select_image(content_id)
                    current = extract_content_id(art.get_current())
                    if current != content_id:
                        raise SamsungError("TV did not confirm selected image as current artwork.")
                    if previous_content_id:
                        deleted = art.delete(previous_content_id)
                        if deleted is not True:
                            raise SamsungError("TV did not confirm deletion of previous app image.")
                    return content_id
            except SamsungError:
                raise
            except Exception as exc:
                raise SamsungError("Could not upload/select TV artwork.") from exc
        finally:
            close = getattr(art, "close", None)
            if close:
                close()


def _upload_select_replace_worker(
    config: SamsungConfig,
    image_path: str,
    previous_content_id: Optional[str],
    result_queue,
) -> None:
    try:
        content_id = SamsungFrame(config)._upload_select_replace_inline(
            Path(image_path), previous_content_id
        )
        result_queue.put(("ok", content_id))
    except Exception as exc:
        result_queue.put(("error", str(exc)))
