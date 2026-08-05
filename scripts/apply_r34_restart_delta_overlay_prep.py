from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/apply_r34_runtime_behavior_health.py"
body = TARGET.read_text(encoding="utf-8")

ROBUST_MARKER = "restart_delta_compact_anchor"
if ROBUST_MARKER in body:
    print("r34 restart-delta overlay prep: already patched")
    raise SystemExit(0)

start = body.find("    old_container = '''")
if start < 0:
    start = body.find(
        "    health = replace_once(\n"
        "        health,\n"
        "        '''            restart_count: value"
    )
if start < 0:
    raise SystemExit("r34 restart-delta overlay prep could not find the old assignment block")

next_anchor = (
    "    health = replace_once(\n"
    "        health,\n"
    "        '''    } else if containers.iter()"
)
end = body.find(next_anchor, start)
if end < 0:
    raise SystemExit("r34 restart-delta overlay prep could not find the next semantic block")

robust = '''    restart_delta_formatted_anchor = \'\'\'            restart_count: value
                .get("RestartCount")
                .and_then(Value::as_u64)
                .unwrap_or(0),
            cpu:\'\'\'
    restart_delta_compact_anchor = \'\'\'            restart_count: value.get("RestartCount").and_then(Value::as_u64).unwrap_or(0),
            cpu:\'\'\'
    restart_delta_formatted_replacement = \'\'\'            restart_count: value
                .get("RestartCount")
                .and_then(Value::as_u64)
                .unwrap_or(0),
            restart_delta: observe_restart_delta_r34(
                &id,
                value
                    .get("RestartCount")
                    .and_then(Value::as_u64)
                    .unwrap_or(0),
            ),
            cpu:\'\'\'
    restart_delta_compact_replacement = \'\'\'            restart_count: value.get("RestartCount").and_then(Value::as_u64).unwrap_or(0),
            restart_delta: observe_restart_delta_r34(
                &id,
                value.get("RestartCount").and_then(Value::as_u64).unwrap_or(0),
            ),
            cpu:\'\'\'
    if restart_delta_formatted_anchor in health:
        health = health.replace(
            restart_delta_formatted_anchor,
            restart_delta_formatted_replacement,
            1,
        )
    elif restart_delta_compact_anchor in health:
        health = health.replace(
            restart_delta_compact_anchor,
            restart_delta_compact_replacement,
            1,
        )
    else:
        raise SystemExit("r34 anchor missing: restart delta assignment (formatted or compact)")
'''

TARGET.write_text(body[:start] + robust + body[end:], encoding="utf-8")
print("r34 restart-delta overlay prep: PATCHED")
