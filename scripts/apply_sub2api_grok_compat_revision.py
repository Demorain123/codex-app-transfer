from __future__ import annotations

import json
import re
import runpy
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


# CAS-AUTO-REVIEW-R24: compose the feature as a replayable thin overlay.
# Preflight hardening first repairs generator-anchor drift against the current r23
# tree; postflight hardening validates/fixes generated output (snapshot ordering,
# metadata serialization). Existing Apply/Windows/pristine flows already invoke
# this revision script last, so no duplicate workflow-specific implementation is needed.
for overlay_script in [
    "scripts/apply_auto_review_model_overlay_r24_hardening.py",
    "scripts/apply_auto_review_model_overlay_r24.py",
    "scripts/apply_auto_review_model_overlay_r24_hardening.py",
]:
    overlay_path = ROOT / overlay_script
    if overlay_path.exists():
        print(f"applying {overlay_script}")
        runpy.run_path(str(overlay_path), run_name="__main__")

# CAS-AUTO-REVIEW-R24-MATERIALIZATION-GATE: do not let CI/package builds continue
# with the half-generated state that previously committed ApplyConfig/call-sites but
# omitted the generated module, module registration, or provider helper. Workflows
# intentionally replay this revision script, so validate the complete generated tree
# immediately after replay and fail with a precise error before Rust compilation.
r24_required_markers = {
    "crates/codex_integration/src/auto_review_overlay.rs": "CAS-AUTO-REVIEW-R24",
    "crates/codex_integration/src/lib.rs": "pub mod auto_review_overlay; // CAS-AUTO-REVIEW-R24",
    "crates/codex_integration/src/apply.rs": "crate::auto_review_overlay::apply_auto_review_overrides(",
    "src-tauri/src/admin/handlers/providers/mod.rs": "provider_auto_review_model_overrides",
    "src-tauri/src/admin/services/desktop/snapshot.rs": "auto_review_model_overrides: Some(&target.auto_review_model_overrides)",
}
for rel_path, marker in r24_required_markers.items():
    candidate = ROOT / rel_path
    if not candidate.is_file():
        raise SystemExit(f"r24 materialization missing generated file: {rel_path}")
    content = candidate.read_text(encoding="utf-8")
    if marker not in content:
        raise SystemExit(f"r24 materialization missing marker in {rel_path}: {marker}")
print("r24 materialization gate: complete")

# CAS-RUNTIME-DIAG-R26-COMPOSE: r26 is deliberately a diagnostics-only layer stacked
# on the latest r24 head. Keep it optional so the same revision patcher remains usable
# on r24 itself; the r26 branch carries the overlay asset and therefore materializes it
# before any visible version identity is changed.
r26_overlay = ROOT / "scripts/apply_runtime_diag_r26.py"
if r26_overlay.exists():
    print("applying scripts/apply_runtime_diag_r26.py")
    runpy.run_path(str(r26_overlay), run_name="__main__")
    r26_required_markers = {
        "src-tauri/src/runtime_diag.rs": "CAS-RUNTIME-DIAG-R26",
        "src-tauri/src/main.rs": "CAS-RUNTIME-DIAG-R26-START",
        "crates/proxy/src/forward.rs": "CAS-SUBAGENT-FAILURE-CHAIN-R26-RESULT",
    }
    for rel_path, marker in r26_required_markers.items():
        candidate = ROOT / rel_path
        if not candidate.is_file():
            raise SystemExit(f"r26 materialization missing generated file: {rel_path}")
        content = candidate.read_text(encoding="utf-8")
        if marker not in content:
            raise SystemExit(f"r26 materialization missing marker in {rel_path}: {marker}")
    print("r26 materialization gate: complete")

revision = REVISION_FILE.read_text(encoding="utf-8").strip()
if not revision.isdigit() or int(revision) < 1:
    raise SystemExit("SUB2API_GROK_COMPAT_REVISION.txt must contain a positive integer")

# The Tauri/MSI build number must be numeric. Keep the official semantic version
# as the base and use +N for the compat revision (for example 2.4.5+3).
tauri_path = ROOT / "src-tauri/tauri.conf.json"
tauri = json.loads(tauri_path.read_text(encoding="utf-8"))
raw_version = str(tauri.get("version", "")).strip()
if not raw_version:
    raise SystemExit("tauri.conf.json has no version")
base_version = raw_version.split("+", 1)[0]
app_version = f"{base_version}+{revision}"
display_revision = f"r{revision}"

# UI layout invariant:
# ProviderFormModal's .pf is a constrained-height column flex container. The
# compat card also has overflow:hidden, which makes its automatic flex minimum
# size zero; under vertical pressure WebView2 may therefore shrink the whole
# card down to its border (the exact symptom is a single blue line). Prevent
# that by making the card a non-shrinking flex item so the parent scrolls it.
path = "frontend/src/components/provider/Sub2ApiGrokCompatControls.vue"
text = read(path)
if not re.search(r"\.compat-card\s*\{[^}]*\bflex-shrink\s*:\s*0\s*;", text, re.S):
    text, n = re.subn(
        r"(\.compat-card\s*\{\s*\n)",
        r"\1  flex-shrink: 0;\n",
        text,
        count=1,
    )
    if n != 1:
        raise SystemExit("could not install non-shrinking compat-card layout invariant")
if not re.search(r"\.compat-card\s*\{[^}]*\bflex-shrink\s*:\s*0\s*;", text, re.S):
    raise SystemExit("compat card can still flex-collapse after revision patch")
write(path, text)

# UI visibility invariant:
# The highlighted Responses segment and the compat card MUST read the exact same
# reactive value. Do not introduce a second computed gate here; that made stale
# or partially-generated builds much harder to diagnose.
path = "frontend/src/components/provider/ProviderFormModal.vue"
text = read(path)
# Remove historical/computed visibility declarations if present. The first-install
# UI overlay on a pristine official checkout still emits the original multiline
# `isCustomProvider && apiFormat === responses` computed gate; already-generated
# compat branches may instead contain one of the later one-line forms. Revision
# normalization must accept all of them so the complete overlay stack is replayable
# directly from pristine upstream before any intermediate rustfmt/build step.
text = re.sub(
    r"\n//[^\n]*Responses provider[^\n]*\n(?://[^\n]*\n){0,3}const\s+showSub2apiGrokCompat\s*=\s*computed\([^\n]*\)\n",
    "\n",
    text,
    count=1,
)
text = re.sub(
    r"\nconst\s+showSub2apiGrokCompat\s*=\s*computed\(\(\)\s*=>\s*form\.apiFormat\s*===\s*'responses'\)\n",
    "\n",
    text,
    count=1,
)
text = re.sub(
    r"\n//\s*CAS-SUB2API-GROK-COMPAT-HOOK:[^\n]*\n"
    r"const\s+showSub2apiGrokCompat\s*=\s*computed\(\s*\n"
    r"\s*\(\)\s*=>\s*isCustomProvider\.value\s*&&\s*form\.apiFormat\s*===\s*'responses',?\s*\n"
    r"\s*\)\s*\n",
    "\n",
    text,
    count=1,
)
# Defensive fallback for the same multiline computed gate if an older UI overlay
# omitted or reworded the preceding comment. Keep the pattern intentionally narrow
# to this exact variable and `isCustomProvider && apiFormat` expression.
text = re.sub(
    r"\nconst\s+showSub2apiGrokCompat\s*=\s*computed\(\s*\n"
    r"\s*\(\)\s*=>\s*isCustomProvider\.value\s*&&\s*form\.apiFormat\s*===\s*'responses',?\s*\n"
    r"\s*\)\s*\n",
    "\n",
    text,
    count=1,
)
text = text.replace(
    'v-if="showSub2apiGrokCompat"',
    'v-if="form.apiFormat === \'responses\'"',
)
if 'v-if="form.apiFormat === \'responses\'"' not in text:
    raise SystemExit("compat card is not directly gated by form.apiFormat === 'responses'")
if "showSub2apiGrokCompat" in text:
    raise SystemExit("legacy showSub2apiGrokCompat gate still exists after revision patch")
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
