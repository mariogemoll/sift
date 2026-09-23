"""The sift command line."""

import argparse

import uvicorn

from sift.settings import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="sift")
    subcommands = parser.add_subparsers(dest="command", required=True)

    serve = subcommands.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    subcommands.add_parser("settings", help="print the resolved configuration")

    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run("sift.api.app:app", host=args.host, port=args.port, reload=args.reload)
    else:
        for field, value in get_settings().model_dump().items():
            print(f"{field}={value}")
