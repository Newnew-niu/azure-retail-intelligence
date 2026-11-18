"""The web app's API types are generated from web/openapi.json, so it must match the live schema."""
import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_exporter():
    spec = importlib.util.spec_from_file_location("export_openapi", PROJECT_ROOT / "scripts" / "export_openapi.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_openapi_file_matches_the_api():
    exporter = load_exporter()
    committed = exporter.OUTPUT.read_text(encoding="utf-8")
    assert committed == exporter.openapi_text(), "Run: python scripts/export_openapi.py, then npm run gen:api in web/"
