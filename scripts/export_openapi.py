"""Write the API's OpenAPI schema to web/openapi.json, the contract the web app's types come from.

    python scripts/export_openapi.py

Run it after changing an endpoint or a response model, then `npm run gen:api` in web/.
serving/tests/test_openapi_contract.py fails while the file is out of date.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from serving.api.main import create_app  # noqa: E402
from serving.core.config import Settings  # noqa: E402

OUTPUT = PROJECT_ROOT / "web" / "openapi.json"


def openapi_text() -> str:
    """The schema does not depend on settings or data, so default settings are enough."""
    return json.dumps(create_app(Settings()).openapi(), indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    OUTPUT.write_bytes(openapi_text().encode("utf-8"))
    print(f"Wrote {OUTPUT.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
