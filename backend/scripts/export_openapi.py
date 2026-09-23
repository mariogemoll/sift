#!/usr/bin/env python
"""Write the OpenAPI document the TypeScript client is generated from.

The schema is a build artifact of the Python app, checked in so a drift between
the API and the client is a diff in a pull request rather than a runtime
surprise.
"""

import json
import sys
from pathlib import Path

from sift.api.app import create_app

DESTINATION = Path(__file__).resolve().parents[2] / "openapi.json"


def main() -> int:
    document = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        current = DESTINATION.read_text() if DESTINATION.exists() else ""
        if current != document:
            print(
                f"{DESTINATION.name} is stale; run `python scripts/export_openapi.py`",
                file=sys.stderr,
            )
            return 1
        print(f"{DESTINATION.name} is up to date")
        return 0
    DESTINATION.write_text(document)
    print(f"wrote {DESTINATION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
