"""Command-line entrypoint for Photo Hub."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .config import ConfigError, load_config
from .samsung import SamsungError
from .service import PhotoHubService
from .store import Store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Photo Hub email-to-frame service.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("~/.config/photo-hub/config.json"),
        help="Path to Photo Hub JSON config.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("run", help="Run polling service forever.")
    subcommands.add_parser("once", help="Process one mailbox/pending-TV pass.")
    subcommands.add_parser("check-config", help="Load config and initialize local state.")
    subcommands.add_parser("status", help="Show pending TV job and recent mailbox results.")
    subcommands.add_parser("tv-status", help="Check whether the Samsung Frame is in Art Mode.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print("Config error: {}".format(exc), file=sys.stderr)
        raise SystemExit(2) from exc
    service = PhotoHubService(config)
    if args.command == "run":
        service.run_forever()
    elif args.command == "once":
        service.run_once()
    elif args.command == "check-config":
        print("Photo Hub config OK. State dir: {}".format(config.paths.state_dir))
    elif args.command == "status":
        store = Store(config.paths.state_dir / "photo-hub.sqlite3")
        pending = store.get_pending_tv()
        current = store.get_current_tv_content_id()
        print("State dir: {}".format(config.paths.state_dir))
        print("Pending TV job: {}".format("yes" if pending else "no"))
        if pending:
            print("  message uid: {}".format(pending.message_uid))
            print("  image path: {}".format(pending.image_path))
        print("Current app TV content id: {}".format(current or "none"))
        print("Recent processed messages:")
        for row in store.recent_processed():
            error = " error={}".format(row["error"]) if row["error"] else ""
            print(
                "  {} uid={} status={}{}".format(
                    row["created_at"], row["uid"], row["status"], error
                )
            )
    elif args.command == "tv-status":
        try:
            mode = service.tv.is_art_mode()
        except SamsungError as exc:
            print("TV error: {}".format(exc), file=sys.stderr)
            raise SystemExit(1) from exc
        print("TV Art Mode: {}".format("on" if mode else "off"))


if __name__ == "__main__":
    main()
