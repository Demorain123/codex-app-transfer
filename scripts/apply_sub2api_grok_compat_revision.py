from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION_FILE = ROOT / "SUB2API_GROK_COMPAT_REVISION.txt"
VERSION_FILE = ROOT / "SUB2API_GROK_COMPAT_VERSION.txt"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    p = ROOT / path
    p.write_text(text, encoding="utf-8")
    print(f"patched {path}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old == new or new in text:
        return text
    if old not in text:
        raise SystemExit(f"anchor not found: {label}")
    return text.replace(old, new, 1)


revision = REVISION_FILE.read_text(encoding="utf-8").strip()
if not revision.isdigit() or int(revision) < 1:
    raise SystemExit("SUB2API_GROK_COMPAT_REVISION.txt must contain a positive integer")

# The Tauri/MSI build number must be numeric. Keep the official semantic version
# as the base and use +N for the compat revision (for example 2.4.5+2).
tauri_path = ROOT / "src-tauri/tauri.conf.json"
tauri = json.loads(tauri_path.read_text(encoding="utf-8"))
raw_version = str(tauri.get("version", "")).strip()
if not raw_version:
    raise SystemExit("tauri.conf.json has no version")
base_version = raw_version.split("+", 1)[0]
app_version = f"{base_version}+{revision}"
display_revision = f"r{revision}"

# Make the compat card impossible to hide merely because a provider gets
# classified as a preset/custom provider differently. Match the actual Vue
# expression rather than surrounding comments/rustfmt layout so this remains
# stable when replayed onto pristine/future upstream sources.
path = "frontend/src/components/provider/ProviderFormModal.vue"
text = read(path)
visible_marker = "const showSub2apiGrokCompat = computed(() => form.apiFormat === 'responses')"
if visible_marker not in text:
    text, n = re.subn(
        r"const\s+showSub2apiGrokCompat\s*=\s*computed\(\s*\(\)\s*=>\s*isCustomProvider\.value\s*&&\s*form\.apiFormat\s*===\s*'responses'\s*,?\s*\)",
        visible_marker,
        text,
        count=1,
    )
    if n != 1:
        raise SystemExit("failed to install Responses-only compat-card visibility rule")
write(path, text)

# Tauri's version drives the app/package version. Keep the identifier unchanged
# so provider/usage data survives official <-> compat reinstalls.
tauri["version"] = app_version
for window in tauri.get("app", {}).get("windows", []):
    if window.get("label") == "main":
        window["title"] = f"Codex App Transfer — Sub2API Grok Compat {display_revision} — v{app_version}"
tauri_path.write_text(json.dumps(tauri, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("patched src-tauri/tauri.conf.json")

# Keep Cargo's package version aligned with Tauri. Cargo accepts SemVer build
# metadata and the numeric +N also maps cleanly to the Windows MSI build number.
path = "src-tauri/Cargo.toml"
text = read(path)
text, n = re.subn(
    r'(?ms)(\[package\]\s+name\s*=\s*"codex-app-transfer"\s+version\s*=\s*)"[^"]+"',
    rf'\1"{app_version}"',
    text,
    count=1,
)
if n != 1:
    raise SystemExit("could not update src-tauri/Cargo.toml package version")
write(path, text)

# Cargo.lock records the root package version. Update it deterministically so CI
# does not create an untracked lockfile change later.
path = "Cargo.lock"
text = read(path)
text, n = re.subn(
    r'(?ms)(\[\[package\]\]\s+name\s*=\s*"codex-app-transfer"\s+version\s*=\s*)"[^"]+"',
    rf'\1"{app_version}"',
    text,
    count=1,
)
if n == 1:
    write(path, text)
else:
    print("warning: root codex-app-transfer package entry not found in Cargo.lock; cargo will reconcile it")

# Visible identity in both the main UI and the native/macOS title bar.
path = "frontend/src/i18n/zh.ts"
text = read(path)
text = re.sub(
    r'("compat\.buildBadge"\s*:\s*)"[^"]*"',
    rf'\1"Sub2API Grok Compat {display_revision} · v{app_version}"',
    text,
    count=1,
)
write(path, text)

path = "frontend/src/i18n/en.ts"
text = read(path)
text = re.sub(
    r'("compat\.buildBadge"\s*:\s*)"[^"]*"',
    rf'\1"Sub2API Grok Compat {display_revision} · v{app_version}"',
    text,
    count=1,
)
write(path, text)

path = "frontend/src/layout/AppLayout.vue"
text = read(path)
text = re.sub(
    r'Codex App Transfer — Sub2API Grok Compat(?: r\d+)?(?: — v[^<]+)?',
    f"Codex App Transfer — Sub2API Grok Compat {display_revision} — v{app_version}",
    text,
    count=1,
)
write(path, text)

VERSION_FILE.write_text(
    f"official_base={base_version}\ncompat_revision={revision}\napp_version={app_version}\n",
    encoding="utf-8",
)
print(f"compat version: {app_version} ({display_revision}, official base {base_version})")
