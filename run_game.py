#!/usr/bin/env python3
"""Touchline Manager entry point.

Starts a local HTTP server for the game UI and opens the browser.
Run ``python run_game.py --seed 7`` to use a specific world seed.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Touchline Manager - a fictional football management game")
    parser.add_argument(
        "--host",
        default=os.environ.get("HOST", "127.0.0.1"),
        help="bind host (default 127.0.0.1, or $HOST)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "8765")),
        help="bind port (default 8765, or $PORT)",
    )
    parser.add_argument("--seed", type=int, default=42, help="world generation seed (default 42)")
    parser.add_argument("--save-dir", default=os.environ.get("SAVE_DIR", ""), help="directory for career saves")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    sys.path.insert(0, ".")

    from manager.api.service import GameService
    from manager.ui.server import create_server, open_browser

    save_dir = Path(args.save_dir) if args.save_dir else None
    address = (args.host, args.port)
    server = create_server(GameService(save_dir=save_dir), address)
    url = f"http://{args.host}:{args.port}"

    print("=" * 60)
    print(" Touchline Manager - fictional football management game")
    print(f" Playing on: {url}")
    print(f" Seed:       {args.seed}")
    print(" Press Ctrl+C to stop.")
    print("=" * 60)

    if not args.no_browser:
        open_browser(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())