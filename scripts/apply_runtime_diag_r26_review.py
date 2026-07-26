from __future__ import annotations

import re
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
if 'name.eq_ignore_ascii_case("chatgpt.exe")' not in text:
    text, count = re.subn(
        r'(?m)^(\s*)if\s+name\.eq_ignore_ascii_case\("codex\.exe"\)\s*\{\s*$',
        r'\1if name.eq_ignore_ascii_case("codex.exe")\n\1    || name.eq_ignore_ascii_case("chatgpt.exe")\n\1{',
        text,
        count=1,
    )
    if count != 1:
        raise SystemExit("r26 process review anchor missing: codex.exe predicate")
print("r26 review: ChatGPT.exe + codex.exe process scope ready")

# Include only the executable image basename in lifecycle records; this is useful
# to distinguish shell vs app-server while remaining much less sensitive than a
# process command line.
for event in ["process_started", "process_exited"]:
    expected = f'event = "{event}",'
    image_marker = 'image = %row.name,'
    event_pos = text.find(expected)
    if event_pos < 0:
        raise SystemExit(f"r26 image-name review anchor missing for {event}")
    window_end = text.find('"Codex runtime process', event_pos)
    if window_end < 0:
        window_end = min(len(text), event_pos + 500)
    window = text[event_pos:window_end]
    if image_marker not in window:
        text = text[: event_pos + len(expected)] + "\n                image = %row.name," + text[event_pos + len(expected) :]
print("r26 review: executable image basename fields ready")

# Once ChatGPT.exe is included, >1 total runtime process is expected. Keep the
# anomaly specifically scoped to multiple codex.exe runtimes, which is the useful
# orphan/app-server signal we are trying to diagnose.
if "let previous_codex_count = previous" not in text:
    pattern = re.compile(
        r'(?ms)^\s*if\s+current\.len\(\)\s*>\s*1\s*&&\s*previous\.len\(\)\s*<=\s*1\s*\{\s*'
        r'tracing::warn!\(\s*'
        r'target:\s*"codex_runtime_diag",\s*'
        r'event\s*=\s*"multiple_codex_processes",\s*'
        r'codex_process_count\s*=\s*current\.len\(\)\s+as\s+u64,\s*'
        r'"multiple codex\.exe runtime candidates detected; diagnostic only"\s*'
        r'\);\s*'
        r'\}\s*'
    )
    replacement = '''    let codex_count = current
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
    text, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise SystemExit("r26 multiple-codex review anchor missing")
print("r26 review: orphan codex.exe anomaly scope ready")

# The old acceptance matrix explicitly called out stream disconnects. Keep this
# separate from generic `reconnecting` so one can see the cause -> reconnect pair.
if '"stream_disconnected"' not in text:
    text, count = re.subn(
        r'(?m)^(\s*)\("response\.failed",\s*"response_failed",\s*"WARN"\),\s*$',
        r'\1("stream disconnected", "stream_disconnected", "WARN"),\n\1("response.failed", "response_failed", "WARN"),',
        text,
        count=1,
    )
    if count != 1:
        raise SystemExit("r26 stream-disconnected review anchor missing")
print("r26 review: stream_disconnected classifier ready")

# CAS-RUNTIME-DIAG-R26-REVIEW-PRIVACY:
# Do not persist a non-cryptographic fingerprint of the full native log line.
# UUID fingerprints already provide cross-line correlation; line byte length is
# enough to distinguish repeated/large records without deriving anything from
# the actual text contents.
if "let line_bytes = line.len() as u64;" not in text:
    text, count = re.subn(
        r'(?m)^\s*let\s+line_fp\s*=\s*format!\("\{:016x\}",\s*fnv64\(line\.as_bytes\(\)\)\);\s*$',
        '    let line_bytes = line.len() as u64;',
        text,
        count=1,
    )
    if count != 1:
        raise SystemExit("r26 privacy review anchor missing: line fingerprint declaration")
text = re.sub(r'\bline_fp\s*=\s*%line_fp\s*,', 'line_bytes,', text)
if "line_fp = %line_fp" in text:
    raise SystemExit("r26 privacy review left a raw-line fingerprint field")
print("r26 review: raw-line fingerprint removed")

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
