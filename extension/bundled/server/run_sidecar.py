from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from app.main import create_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Trainer FastAPI sidecar.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reload", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server_root = Path(__file__).resolve().parent
    if args.reload:
        uvicorn.run(
            "app.main:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            log_level="info",
            reload=True,
            reload_dirs=[str(server_root)],
        )
        return
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
