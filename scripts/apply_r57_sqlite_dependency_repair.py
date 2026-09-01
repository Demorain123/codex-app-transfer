from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARGO = ROOT / "src-tauri/Cargo.toml"
ADAPTERS_CARGO = ROOT / "crates/adapters/Cargo.toml"

BAD = 'rusqlite = { version = "0.31", features = ["bundled"] }'
GOOD = 'rusqlite = { version = "0.40", features = ["bundled"] }'

adapters = ADAPTERS_CARGO.read_text(encoding="utf-8")
if GOOD not in adapters:
    raise SystemExit(
        "r57 sqlite repair: adapters no longer use the expected rusqlite 0.40 bundled baseline; refusing to guess"
    )

cargo = CARGO.read_text(encoding="utf-8")
changed = False

if BAD in cargo:
    cargo = cargo.replace(BAD, GOOD)
    changed = True
elif GOOD not in cargo:
    win_anchor = '''[target.'cfg(target_os = "windows")'.dependencies]\nwindows = { version = "0.62", features = [\n'''
    if win_anchor not in cargo:
        raise SystemExit("r57 sqlite repair: Windows dependency anchor missing")
    cargo = cargo.replace(
        win_anchor,
        '''[target.'cfg(target_os = "windows")'.dependencies]\n# r57: reuse the workspace's existing rusqlite/libsqlite3-sys line.\n# Keep the version aligned with crates/adapters to avoid duplicate `links = sqlite3`.\nrusqlite = { version = "0.40", features = ["bundled"] }\nwindows = { version = "0.62", features = [\n''',
        1,
    )
    changed = True

# Reject any stale r57 0.31 line even if another 0.40 line also exists.
if BAD in cargo:
    raise SystemExit("r57 sqlite repair: stale rusqlite 0.31 dependency remains")
if GOOD not in cargo:
    raise SystemExit("r57 sqlite repair: rusqlite 0.40 dependency missing after repair")

if changed:
    CARGO.write_text(cargo, encoding="utf-8")
    print("R57 SQLITE DEPENDENCY REPAIR: changed src-tauri rusqlite 0.31 -> 0.40")
else:
    print("R57 SQLITE DEPENDENCY REPAIR: already aligned on rusqlite 0.40")

print("- src-tauri and crates/adapters now share rusqlite 0.40 + bundled")
print("- only one compatible libsqlite3-sys links=sqlite3 line remains in the dependency graph")
