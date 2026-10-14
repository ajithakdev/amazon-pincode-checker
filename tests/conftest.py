import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if "playwright.sync_api" not in sys.modules:
    pw = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = lambda *a, **k: None
    sync_api.TimeoutError = type("TimeoutError", (Exception,), {})
    sync_api.Error = type("Error", (Exception,), {})
    pw.sync_api = sync_api
    sys.modules["playwright"] = pw
    sys.modules["playwright.sync_api"] = sync_api
