"""The sift command line."""

import argparse
import secrets
import sys
from getpass import getpass

import uvicorn

from sift.auth.passphrase import SALT_BYTES, hash_passphrase
from sift.settings import get_settings


def _read_passphrase(from_stdin: bool) -> str:
    """The phrase to hash, typed twice at a terminal or piped in once."""
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass("Passphrase: ")
    if not first:
        raise SystemExit("empty passphrase")
    if first != getpass("Again: "):
        raise SystemExit("they did not match")
    return first


def main() -> None:
    parser = argparse.ArgumentParser(prog="sift")
    subcommands = parser.add_subparsers(dest="command", required=True)

    serve = subcommands.add_parser("serve", help="run the HTTP API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    subcommands.add_parser("settings", help="print the resolved configuration")

    # Only the line to export lands on stdout, so this can be appended to a
    # .env file or piped into `aws secretsmanager put-secret-value`.
    passphrase = subcommands.add_parser(
        "passphrase", help="hash a passphrase into SIFT_PASSPHRASE_HASH"
    )
    passphrase.add_argument(
        "--stdin", action="store_true", help="read the phrase from stdin instead of prompting"
    )

    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run("sift.api.app:app", host=args.host, port=args.port, reload=args.reload)
    elif args.command == "passphrase":
        phrase = _read_passphrase(args.stdin)
        print(f"SIFT_PASSPHRASE_HASH={hash_passphrase(phrase, secrets.token_bytes(SALT_BYTES))}")
    else:
        for field, value in get_settings().model_dump().items():
            print(f"{field}={value}")
