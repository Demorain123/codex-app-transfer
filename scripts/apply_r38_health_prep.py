from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
text = path.read_text(encoding="utf-8")

# Normalize the r37 build_snapshot overall block before the r38 semantic overlay.
# This deliberately mirrors the inherited r37 behavior and only repairs formatting/
# replay drift so the r38 replacement remains exact and reviewable.
start_marker = "    let overall = overall_status([\n"
end_marker = "    // CAS-R37-SNAPSHOT-PREP\n"
start = text.find(start_marker)
end = text.find(end_marker, start + 1) if start >= 0 else -1
if start < 0 or end < 0 or end <= start:
    raise SystemExit("r38 health prep: could not locate inherited r37 overall block")

normalized = '''    let overall = overall_status([
        &codex,
        &session,
        &mcp,
        &transfer,
        &gateway,
        &runtime.layer,
        &account,
        &upstream,
        &diagnosis,
    ]);
    let overall_summary = if !matches!(diagnosis.code.as_str(), "fault_none" | "fault_no_evidence")
    {
        format!("最可能故障归因：{}", diagnosis.summary)
    } else {
        match overall.as_str() {
            "error" => "链路存在明确故障，展开建议可查看最可能的阻断层".to_owned(),
            "degraded" => "链路可用性下降或有请求等待，需要继续观察".to_owned(),
            "ok" => "轻量诊断未发现明确故障".to_owned(),
            _ => "当前证据不足，等待一次真实请求后可获得更多被动证据".to_owned(),
        }
    };
'''
text = text[:start] + normalized + text[end:]
path.write_text(text, encoding="utf-8")
print("r38 health prep: normalized inherited overall block")
