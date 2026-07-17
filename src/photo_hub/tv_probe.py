"""Safe Samsung The Frame capability probe for the Photo Hub feasibility gate."""

from __future__ import annotations

import argparse
import base64
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import ssl
import sys
from typing import Any, Dict, Iterable, List, Optional
import uuid


class ProbeError(RuntimeError):
    """A safe, user-facing probe failure."""


@dataclass
class ProbeState:
    """Only Samsung content identifiers created by this probe."""

    owned_content_ids: List[str] = field(default_factory=list)
    current_content_id: Optional[str] = None
    deleted_content_ids: List[str] = field(default_factory=list)
    updated_at: Optional[str] = None

    def mark_uploaded(self, content_id: str) -> None:
        if content_id not in self.owned_content_ids:
            self.owned_content_ids.append(content_id)
        self.updated_at = now_iso()

    def mark_displayed(self, content_id: str) -> None:
        if content_id not in self.owned_content_ids:
            raise ProbeError("Refusing to mark a non-probe content ID as displayed.")
        self.current_content_id = content_id
        self.updated_at = now_iso()

    def mark_deleted(self, content_id: str) -> None:
        if content_id not in self.owned_content_ids:
            raise ProbeError("Refusing to delete content not recorded as probe-owned.")
        self.owned_content_ids.remove(content_id)
        if content_id not in self.deleted_content_ids:
            self.deleted_content_ids.append(content_id)
        if self.current_content_id == content_id:
            self.current_content_id = None
        self.updated_at = now_iso()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(path: Path) -> ProbeState:
    if not path.exists():
        return ProbeState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ProbeState(
            owned_content_ids=list(raw.get("owned_content_ids", [])),
            current_content_id=raw.get("current_content_id"),
            deleted_content_ids=list(raw.get("deleted_content_ids", [])),
            updated_at=raw.get("updated_at"),
        )
    except (OSError, ValueError, TypeError) as exc:
        raise ProbeError("Cannot read probe state file: {}".format(path)) from exc


def save_state(path: Path, state: ProbeState) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = json.dumps(asdict(state), indent=2, sort_keys=True) + "\n"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def interpret_art_mode(value: Any) -> Optional[bool]:
    """Interpret common Art API response shapes without optimistic guessing."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"on", "true", "art", "artmode", "art_mode"}:
            return True
        if normalized in {"off", "false", "tv", "viewing"}:
            return False
        try:
            return interpret_art_mode(json.loads(value))
        except ValueError:
            return None
    if isinstance(value, dict):
        for key in ("value", "artmode", "art_mode", "status", "current"):
            if key in value:
                result = interpret_art_mode(value[key])
                if result is not None:
                    return result
    return None


def require_active_art_mode(raw_mode: Any) -> None:
    mode = interpret_art_mode(raw_mode)
    if mode is True:
        return
    if mode is False:
        raise ProbeError(
            "TV is not in Art Mode. No upload or display action was performed."
        )
    raise ProbeError(
        "Art Mode response could not be interpreted safely. No upload was performed: "
        + repr(raw_mode)
    )


def extract_content_id(response: Any) -> str:
    """Extract a newly uploaded content ID from known and defensive response shapes."""
    if isinstance(response, dict):
        for key in ("content_id", "contentId", "id"):
            candidate = response.get(key)
            if isinstance(candidate, (str, int)) and str(candidate):
                return str(candidate)
        for candidate in response.values():
            try:
                return extract_content_id(candidate)
            except ProbeError:
                continue
    if isinstance(response, (list, tuple)):
        for candidate in response:
            try:
                return extract_content_id(candidate)
            except ProbeError:
                continue
    if isinstance(response, str):
        if response.strip().isdigit():
            return response.strip()
        try:
            return extract_content_id(json.loads(response))
        except ValueError:
            match = re.search(r"\b(?:MY-|SAM-)?[A-Z0-9][A-Z0-9_-]*\b", response)
            if match:
                return match.group(0)
    raise ProbeError("Upload completed without a recognizable Samsung content ID.")


def render_probe_image(path: Path, sequence: int) -> None:
    from PIL import Image, ImageDraw

    width, height = 3840, 2160
    base_color = (28, 84, 115) if sequence == 1 else (99, 49, 98)
    accent_color = (242, 199, 80) if sequence == 1 else (87, 205, 190)
    image = Image.new("RGB", (width, height), base_color)
    draw = ImageDraw.Draw(image)
    draw.rectangle((130, 130, width - 130, height - 130), outline=accent_color, width=24)
    draw.rectangle((160, height - 620, width - 160, height - 160), fill=(15, 20, 27))
    draw.text((260, height - 510), "PHOTO HUB TV PROBE", fill=(255, 255, 255))
    draw.text((260, height - 410), "TEST IMAGE {}".format(sequence), fill=accent_color)
    draw.text(
        (260, height - 300),
        "Created by the Photo Hub feasibility check. Safe to remove.",
        fill=(255, 255, 255),
    )
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    image.save(str(path), "JPEG", quality=94, optimize=True)
    os.chmod(path, 0o600)


def connect_tv(host: str, port: int, token_file: Path, timeout: int) -> Any:
    try:
        from samsungtvws import SamsungTVWS
    except ImportError as exc:
        raise ProbeError(
            "samsungtvws is not installed. Install the probe environment first."
        ) from exc
    token_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    return SamsungTVWS(
        host=host,
        port=port,
        token_file=str(token_file),
        timeout=timeout,
    )


def connect_art(args: argparse.Namespace) -> Any:
    if args.homebridge_art:
        try:
            from samsungtvws.art import SamsungTVArt
        except ImportError as exc:
            raise ProbeError(
                "samsungtvws Art client is not installed in the probe environment."
            ) from exc
        return SamsungTVArt(
            host=args.host,
            port=8001,
            timeout=args.timeout,
            name="Frame TV",
        )
    tv = connect_tv(args.host, args.port, args.token_file, args.timeout)
    return tv.art()


def close_tv(tv: Any) -> None:
    close = getattr(tv, "close", None)
    if close:
        close()


def summarize_mode(raw: Any) -> str:
    parsed = interpret_art_mode(raw)
    if parsed is True:
        return "art_mode"
    if parsed is False:
        return "active_viewing_or_not_art_mode"
    return "unrecognized: {}".format(repr(raw))


def list_content_ids(available: Iterable[Any]) -> List[str]:
    content_ids: List[str] = []
    for item in available:
        try:
            content_ids.append(extract_content_id(item))
        except ProbeError:
            continue
    return content_ids


def confirm_current_image(art: Any, expected_content_id: str) -> None:
    try:
        current_content_id = extract_content_id(art.get_current())
    except ProbeError as exc:
        raise ProbeError(
            "Unable to confirm the currently displayed artwork after selection."
        ) from exc
    if current_content_id != expected_content_id:
        raise ProbeError(
            "TV did not confirm selected probe image as current artwork "
            "(expected {}, received {}).".format(expected_content_id, current_content_id)
        )


def cmd_preflight(args: argparse.Namespace) -> None:
    print("Host environment:")
    print("  platform: {}".format(platform.platform()))
    print("  architecture: {}".format(platform.machine()))
    print("  python: {}".format(platform.python_version()))
    disk_path = args.state_dir
    while not disk_path.exists() and disk_path != disk_path.parent:
        disk_path = disk_path.parent
    usage = shutil.disk_usage(str(disk_path))
    print("  free_disk_mb: {}".format(round(usage.free / 1024 / 1024)))
    print("TV reachability from this host:")
    for port in (8001, 8002):
        reachable = False
        try:
            with socket.create_connection((args.host, port), timeout=args.timeout):
                reachable = True
        except OSError:
            pass
        print("  {}:{}: {}".format(args.host, port, "reachable" if reachable else "unreachable"))


def read_tv_status(args: argparse.Namespace) -> Dict[str, Any]:
    art = connect_art(args)
    try:
        supported = art.supported()
        raw_mode = art.get_artmode() if supported else None
        content = art.available() if supported else []
        return {
            "supported": bool(supported),
            "mode": summarize_mode(raw_mode),
            "raw_mode": raw_mode,
            "available_count": len(content),
        }
    finally:
        close_tv(art)


def cmd_status(args: argparse.Namespace) -> None:
    status = read_tv_status(args)
    print("Art Mode supported: {}".format(status["supported"]))
    print("Current mode: {}".format(status["mode"]))
    print("Available artwork count: {}".format(status["available_count"]))
    print("Token stored: {}".format(args.token_file.exists()))


def cmd_pair(args: argparse.Namespace) -> None:
    tv = connect_tv(args.host, args.port, args.token_file, args.timeout)
    try:
        tv.open()
    finally:
        close_tv(tv)
    if not args.token_file.exists():
        raise ProbeError(
            "The TV connection opened but did not provide a persisted pairing token."
        )
    os.chmod(args.token_file, 0o600)
    print("Samsung remote pairing token stored: {}".format(args.token_file))


def redact_trace_payload(value: Any, token: Optional[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: ("[redacted]" if key.lower() == "token" else redact_trace_payload(item, token))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_trace_payload(item, token) for item in value]
    if isinstance(value, str) and token:
        return value.replace(token, "[redacted]")
    return value


def cmd_trace_status(args: argparse.Namespace) -> None:
    try:
        import websocket
    except ImportError as exc:
        raise ProbeError("websocket-client is not installed in the probe environment.") from exc

    token = None
    if not args.without_token and args.token_file.exists():
        token = args.token_file.read_text(encoding="utf-8").strip()
    client_name = "Frame TV" if args.as_homebridge else args.client_name
    encoded_name = base64.b64encode(client_name.encode("utf-8")).decode("ascii")
    protocol = "wss" if args.port == 8002 else "ws"
    query = "name={}".format(encoded_name)
    if token:
        query += "&token={}".format(token)
    url = "{}://{}:{}/api/v2/channels/com.samsung.art-app?{}".format(
        protocol, args.host, args.port, query
    )
    sslopt = {"cert_reqs": ssl.CERT_NONE} if args.port == 8002 else {}
    print(
        "Opening Art channel on port {} (token: {}).".format(
            args.port, "present" if token else "omitted"
        )
    )
    requests_sent = 0
    connection = None
    try:
        connection = websocket.create_connection(url, timeout=args.timeout, sslopt=sslopt)
        for _ in range(args.frames):
            try:
                raw = connection.recv()
            except websocket.WebSocketTimeoutException:
                print("Receive timed out while waiting for another Art event.")
                return
            frame = json.loads(raw)
            redacted = redact_trace_payload(frame, token)
            print("Event: {}".format(frame.get("event", "[missing]")))
            print(json.dumps(redacted, sort_keys=True))
            should_send = (
                args.send_after_connect and frame.get("event") == "ms.channel.connect"
            ) or (
                not args.send_after_connect and frame.get("event") == "ms.channel.ready"
            ) or (
                args.retry_after_disconnect
                and requests_sent > 0
                and frame.get("event") == "ms.channel.clientDisconnect"
            )
            if should_send and requests_sent <= int(args.retry_after_disconnect):
                request_data: Dict[str, str] = {"request": "get_artmode_status"}
                if not args.as_homebridge:
                    request_id = str(uuid.uuid4())
                    request_data.update({"id": request_id, "request_id": request_id})
                request = {
                    "method": "ms.channel.emit",
                    "params": {
                        "event": "art_app_request",
                        "to": "host",
                        "data": json.dumps(request_data),
                    },
                }
                connection.send(json.dumps(request))
                requests_sent += 1
                print("Sent read-only get_artmode_status request #{}.".format(requests_sent))
    except (OSError, ValueError, websocket.WebSocketException) as exc:
        raise ProbeError("Raw Art channel trace failed: {}".format(exc)) from exc
    finally:
        if connection is not None:
            connection.close()


def upload_probe_image(args: argparse.Namespace, sequence: int, state: ProbeState) -> str:
    image_path = args.state_dir / "probe-images" / "probe-{}.jpg".format(sequence)
    render_probe_image(image_path, sequence)
    art = connect_art(args)
    try:
        if not art.supported():
            raise ProbeError("This TV did not report Art Mode support.")
        require_active_art_mode(art.get_artmode())
        with image_path.open("rb") as image_file:
            response = art.upload(image_file.read(), file_type="JPEG")
        content_id = extract_content_id(response)
        state.mark_uploaded(content_id)
        save_state(args.state_file, state)
        art.select_image(content_id)
        confirm_current_image(art, content_id)
        state.mark_displayed(content_id)
        save_state(args.state_file, state)
        return content_id
    finally:
        close_tv(art)


def cmd_upload_first(args: argparse.Namespace) -> None:
    state = load_state(args.state_file)
    if state.owned_content_ids:
        raise ProbeError(
            "Probe state already records uploaded content. Use replace or cleanup; "
            "no new image was uploaded."
        )
    content_id = upload_probe_image(args, 1, state)
    print("Uploaded and displayed first probe image: {}".format(content_id))
    print("Restart this command-line session, then run status to validate persisted pairing.")


def cmd_replace(args: argparse.Namespace) -> None:
    state = load_state(args.state_file)
    previous_id = state.current_content_id
    if not previous_id or previous_id not in state.owned_content_ids:
        raise ProbeError("No displayed probe-owned image is recorded for replacement.")
    new_id = upload_probe_image(args, 2, state)
    art = connect_art(args)
    try:
        require_active_art_mode(art.get_artmode())
        if art.delete(previous_id) is not True:
            raise ProbeError("TV did not confirm deletion of prior probe-owned image.")
        state.mark_deleted(previous_id)
        save_state(args.state_file, state)
        remaining_ids = list_content_ids(art.available())
        if previous_id in remaining_ids:
            raise ProbeError(
                "The API returned from delete but the prior probe image is still listed."
            )
    finally:
        close_tv(art)
    print("Uploaded and displayed replacement probe image: {}".format(new_id))
    print("Deleted prior probe-owned image only: {}".format(previous_id))


def cmd_cleanup(args: argparse.Namespace) -> None:
    if not args.confirm:
        raise ProbeError("Cleanup requires --confirm because it deletes TV photos.")
    state = load_state(args.state_file)
    if not state.owned_content_ids:
        print("There are no recorded probe-owned images to delete.")
        return
    art = connect_art(args)
    try:
        for content_id in list(state.owned_content_ids):
            if art.delete(content_id) is not True:
                raise ProbeError(
                    "TV did not confirm deletion of probe-owned image: {}".format(
                        content_id
                    )
                )
            state.mark_deleted(content_id)
            save_state(args.state_file, state)
            print("Deleted probe-owned image: {}".format(content_id))
    finally:
        close_tv(art)


def build_parser() -> argparse.ArgumentParser:
    default_state_dir = Path("~/.local/state/photo-hub/tv-probe").expanduser()
    parser = argparse.ArgumentParser(
        description="Validate Samsung The Frame automation without interrupting viewing."
    )
    parser.add_argument("--host", required=True, help="TV IPv4 address on the Pi's LAN.")
    parser.add_argument(
        "--port",
        type=int,
        choices=(8001, 8002),
        default=8002,
        help="Samsung control port; use 8001 if the TV exposes legacy Art WebSocket support.",
    )
    parser.add_argument(
        "--homebridge-art",
        action="store_true",
        help="Use the working Frame TV Art identity on uncredentialed port 8001.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=default_state_dir,
        help="Private directory for probe state and token.",
    )
    parser.add_argument("--timeout", type=int, default=10)
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("preflight", help="Report Pi suitability and TV port reachability.")
    subcommands.add_parser(
        "pair",
        help="Request a persisted TV pairing token without sending remote-control actions.",
    )
    subcommands.add_parser("status", help="Pair/read Art Mode status without changing the TV.")
    trace = subcommands.add_parser(
        "trace-status",
        help="Trace redacted Art-channel events and optionally issue a read-only status request.",
    )
    trace.add_argument(
        "--without-token",
        action="store_true",
        help="Open Art channel without including the stored Samsung pairing token.",
    )
    trace.add_argument(
        "--send-after-connect",
        action="store_true",
        help="Issue read-only status after channel connect instead of waiting for channel ready.",
    )
    trace.add_argument(
        "--retry-after-disconnect",
        action="store_true",
        help="Retry status once on the same connection after it evicts a stale client.",
    )
    trace.add_argument(
        "--client-name",
        default="SamsungTvRemote",
        help="Art-channel client name shown to the TV.",
    )
    trace.add_argument(
        "--as-homebridge",
        action="store_true",
        help="Use the Frame TV client name and bare status payload from homebridge-samsung-tizen.",
    )
    trace.add_argument("--frames", type=int, default=4)
    subcommands.add_parser(
        "upload-first",
        help="Upload and display probe image 1 only when the TV is already in Art Mode.",
    )
    subcommands.add_parser(
        "replace",
        help="Display probe image 2 and delete the recorded image 1 only.",
    )
    cleanup = subcommands.add_parser("cleanup", help="Delete remaining probe-owned images.")
    cleanup.add_argument("--confirm", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.state_dir = args.state_dir.expanduser()
    args.state_file = args.state_dir / "probe-state.json"
    args.token_file = args.state_dir / "tv-token.txt"
    commands = {
        "preflight": cmd_preflight,
        "pair": cmd_pair,
        "status": cmd_status,
        "trace-status": cmd_trace_status,
        "upload-first": cmd_upload_first,
        "replace": cmd_replace,
        "cleanup": cmd_cleanup,
    }
    try:
        commands[args.command](args)
    except ProbeError as exc:
        print("Probe stopped safely: {}".format(exc), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
