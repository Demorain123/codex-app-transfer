from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REL = "src-tauri/src/admin/handlers/chain_health.rs"
path = ROOT / REL
if not path.is_file():
    raise SystemExit(f"r37 snapshot prep missing file: {REL}")

body = path.read_text(encoding="utf-8")
marker = "// CAS-R37-SNAPSHOT-PREP"
if marker in body:
    print("r37 snapshot prep: already normalized")
    raise SystemExit(0)

start_token = "    let upstream = passive_upstream_layer();\n"
end_token = "\n\n    ChainHealthSnapshot {\n"
start = body.find(start_token)
if start < 0:
    raise SystemExit("r37 snapshot prep: upstream snapshot start not found")
end = body.find(end_token, start)
if end < 0:
    raise SystemExit("r37 snapshot prep: ChainHealthSnapshot boundary not found")

# Normalize only the r36 build_snapshot composition block. This deliberately
# does not change behavior; it gives the r37 overlay a stable replay anchor even
# after rustfmt or prior overlay whitespace changes.
normalized = '''    let upstream = passive_upstream_layer();
    let recommendations = recommendations(&session, &mcp, &transfer, &gateway, &runtime, &upstream);
    let overall = overall_status([
        &codex,
        &session,
        &mcp,
        &transfer,
        &gateway,
        &runtime.layer,
        &upstream,
    ]);
    let overall_summary = match overall.as_str() {
        "error" => "链路存在明确故障，展开建议可查看最可能的阻断层",
        "degraded" => "链路可用性下降或有请求等待，需要继续观察",
        "ok" => "自动无额度探针未发现明确故障",
        _ => "当前证据不足，等待一次真实请求后可获得更多被动证据",
    }
    .to_owned();
'''
body = body[:start] + normalized + marker + body[end:]
path.write_text(body, encoding="utf-8")
print("r37 snapshot prep: normalized")
