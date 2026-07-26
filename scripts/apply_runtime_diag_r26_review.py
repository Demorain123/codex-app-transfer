from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/runtime_diag.rs"

if not TARGET.is_file():
    raise SystemExit("r26 runtime review requires generated src-tauri/src/runtime_diag.rs")

text = TARGET.read_text(encoding="utf-8")
original = text

# CAS-RUNTIME-DIAG-R26-REVIEW-PROCESSES:
# The real Codex Desktop package can expose both ChatGPT.exe (desktop shell) and
# codex.exe (app-server/runtime). Observe both without reading command lines.
old = '                if name.eq_ignore_ascii_case("codex.exe") {\n'
new = (
    '                if name.eq_ignore_ascii_case("codex.exe")\n'
    '                    || name.eq_ignore_ascii_case("chatgpt.exe")\n'
    '                {\n'
)
if old in text:
    text = text.replace(old, new, 1)
elif 'name.eq_ignore_ascii_case("chatgpt.exe")' not in text:
    raise SystemExit("r26 process review anchor missing")

# Include only the executable image basename in lifecycle records; this is useful
# to distinguish shell vs app-server while remaining much less sensitive than a
# process command line.
for event in ["process_started", "process_exited"]:
    marker = f'                event = "{event}",\n'
    replacement = marker + '                image = %row.name,\n'
    if replacement not in text:
        if marker not in text:
            raise SystemExit(f"r26 image-name review anchor missing for {event}")
        text = text.replace(marker, replacement, 1)

# Once ChatGPT.exe is included, >1 total runtime process is expected. Keep the
# anomaly specifically scoped to multiple codex.exe runtimes, which is the useful
# orphan/app-server signal we are trying to diagnose.
old_block = '''    if current.len() > 1 && previous.len() <= 1 {
        tracing::warn!(
            target: "codex_runtime_diag",
            event = "multiple_codex_processes",
            codex_process_count = current.len() as u64,
            "multiple codex.exe runtime candidates detected; diagnostic only"
        );
    }
'''
new_block = '''    let codex_count = current
        .values()
        .filter(|row| row.name.eq_ignore_ascii_case("codex.exe"))
        .count();
    let previous_codex_count = previous
        .values()
        .filter(|row| row.name.eq_ignore_ascii_case("codex.exe"))
        .count();
    if codex_count > 1 && previous_codex_count <= 1 {
        tracing::warn!(
            target: "codex_runtime_diag",
            event = "multiple_codex_processes",
            codex_process_count = codex_count as u64,
            "multiple codex.exe runtime candidates detected; diagnostic only"
        );
    }
'''
if old_block in text:
    text = text.replace(old_block, new_block, 1)
elif "let previous_codex_count = previous" not in text:
    raise SystemExit("r26 multiple-codex review anchor missing")

# The old acceptance matrix explicitly called out stream disconnects. Keep this
# separate from generic `reconnecting` so one can see the cause -> reconnect pair.
needle = '        ("response.failed", "response_failed", "WARN"),\n'
inserted = '        ("stream disconnected", "stream_disconnected", "WARN"),\n' + needle
if '"stream_disconnected"' not in text:
    if needle not in text:
        raise SystemExit("r26 stream-disconnected review anchor missing")
    text = text.replace(needle, inserted, 1)

# CAS-RUNTIME-DIAG-R26-REVIEW-PRIVACY:
# Do not persist a non-cryptographic fingerprint of the full native log line.
# UUID fingerprints already provide cross-line correlation; line byte length is
# enough to distinguish repeated/large records without deriving anything from
# the actual text contents.
old = '    let line_fp = format!("{:016x}", fnv64(line.as_bytes()));\n'
new = '    let line_bytes = line.len() as u64;\n'
if old in text:
    text = text.replace(old, new, 1)
elif "let line_bytes = line.len() as u64;" not in text:
    raise SystemExit("r26 privacy review anchor missing")
text = text.replace('status, line_fp = %line_fp,', 'status, line_bytes,')
if "line_fp = %line_fp" in text:
    raise SystemExit("r26 privacy review left a raw-line fingerprint field")

if text != original:
    TARGET.write_text(text, encoding="utf-8")
    print("patched src-tauri/src/runtime_diag.rs (r26 self-review hardening)")
else:
    print("r26 self-review hardening already applied")

required = [
    'name.eq_ignore_ascii_case("chatgpt.exe")',
    'event = "stream_disconnected"',
    "let previous_codex_count = previous",
    "let line_bytes = line.len() as u64;",
]
final = TARGET.read_text(encoding="utf-8")
for marker in required:
    if marker not in final:
        raise SystemExit(f"r26 self-review materialization missing marker: {marker}")
print("r26 self-review materialization gate: complete")
