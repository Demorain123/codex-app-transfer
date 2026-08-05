from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/apply_r34_runtime_behavior_health.py"
body = TARGET.read_text(encoding="utf-8")

old = '''    old_container = \'\'\'        containers.push(DockerContainerHealth {
            target: target_prefixes
\'\'\'
    new_container = \'\'\'        let restart_count = value
            .get("RestartCount")
            .and_then(Value::as_u64)
            .unwrap_or(0);
        let restart_delta = observe_restart_delta_r34(&id, restart_count);
        containers.push(DockerContainerHealth {
            target: target_prefixes
\'\'\'
    health = replace_once(health, old_container, new_container, "restart delta calculation")
    health = replace_once(
        health,
        \'\'\'            restart_count: value
                .get("RestartCount")
                .and_then(Value::as_u64)
                .unwrap_or(0),
            cpu:\'\'\',
        \'\'\'            restart_count,
            restart_delta,
            cpu:\'\'\',
        "restart delta assignment",
    )
'''

new = '''    health = replace_once(
        health,
        \'\'\'            restart_count: value
                .get("RestartCount")
                .and_then(Value::as_u64)
                .unwrap_or(0),
            cpu:\'\'\',
        \'\'\'            restart_count: value
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
            cpu:\'\'\',
        "restart delta assignment",
    )
'''

if old in body:
    TARGET.write_text(body.replace(old, new, 1), encoding="utf-8")
    print("r34 restart-delta overlay prep: PATCHED")
elif "restart_delta: observe_restart_delta_r34(" in body and "old_container =" not in body:
    print("r34 restart-delta overlay prep: already patched")
else:
    raise SystemExit("r34 restart-delta overlay prep could not identify expected source block")
