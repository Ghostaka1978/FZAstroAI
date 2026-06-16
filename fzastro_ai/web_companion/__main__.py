from __future__ import annotations

import argparse
import os

from .server import DEFAULT_WEB_HOST, DEFAULT_WEB_PORT


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the FZAstro AI Web Companion.")
    parser.add_argument("--host", default=DEFAULT_WEB_HOST)
    parser.add_argument("--port", default=DEFAULT_WEB_PORT, type=int)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload while developing the web companion.",
    )
    parser.add_argument(
        "--lan",
        action="store_true",
        help="Bind to 0.0.0.0 for same-network iPad/Mac/browser access.",
    )
    args = parser.parse_args()

    host = "0.0.0.0" if args.lan else args.host

    if args.lan:
        os.environ["FZASTRO_WEB_ALLOW_LAN"] = "1"

    if args.lan and not os.environ.get("FZASTRO_WEB_TOKEN"):
        print(
            "WARNING: LAN mode exposes the web companion to your local network. "
            "Set FZASTRO_WEB_TOKEN before using this outside a trusted network."
        )

    import uvicorn

    uvicorn.run(
        "fzastro_ai.web_companion.server:app",
        host=host,
        port=args.port,
        reload=bool(args.reload),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
