from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "frontend/src/pages/SettingsPage.vue"
DIST = ROOT / "frontend/dist"
INDEX = DIST / "index.html"
STAMP = DIST / ".cas-r47-custom-temp-ui"

page = PAGE.read_text(encoding="utf-8")
if "CAS-R47-CODEX-CUSTOM-TEMP" not in page:
    raise SystemExit("r47 frontend invalidation: custom-temp UI marker missing")

if not STAMP.exists():
    DIST.mkdir(parents=True, exist_ok=True)
    if INDEX.is_file():
        INDEX.unlink()
        print("r47 custom temp: invalidated stale frontend dist once")
    STAMP.write_text("r47 custom-temp UI requires rebuilt frontend assets\n", encoding="utf-8")
    print("R47 FRONTEND INVALIDATE-ONCE PASS")
else:
    print("r47 custom temp frontend invalidation already recorded; SKIP")
