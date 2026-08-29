from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORWARD = ROOT / "crates/proxy/src/forward.rs"

text = FORWARD.read_text(encoding="utf-8")
old = '"remote_compaction_v2" | "local_compaction_v2" | "compaction"'
new = '"remote_compaction_v2" | "local_compaction_v2"'
if old not in text:
    if new in text and 'CAS-R45-COMPACTION-DETECTOR-SAFETY' in text:
        print("r45 compaction detector safety already applied")
        raise SystemExit(0)
    raise SystemExit("r45 compaction detector safety anchor missing")

text = text.replace(old, new, 1)
text = text.replace(
    '// CAS-R45-RESPONSES-SEMANTIC-TERMINAL',
    '// CAS-R45-COMPACTION-DETECTOR-SAFETY\n'
    '// Free-text value "compaction" is not a helper signal; only structural type=compaction\n'
    '// or explicit *_compaction_v2 feature markers may trigger model rebinding.\n'
    '// CAS-R45-RESPONSES-SEMANTIC-TERMINAL',
    1,
)
text = text.replace(
    '"content":"please discuss compaction and summaries"',
    '"content":"compaction"',
    1,
)
FORWARD.write_text(text, encoding="utf-8")
print("R45 COMPACTION DETECTOR SAFETY PASS")
