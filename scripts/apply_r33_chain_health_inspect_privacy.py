from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
MARKER = "CAS-R33-CHAIN-HEALTH-INSPECT-PRIVACY"

body = TARGET.read_text(encoding="utf-8")
if MARKER in body:
    print("r33 Docker inspect privacy projection already applied")
    raise SystemExit(0)

old = '''    let mut args = vec!["inspect".to_owned()];
    args.extend(ids.iter().take(MAX_CONTAINERS).cloned());
    let result = run_command("docker", &args, Duration::from_secs(4)).await;
    if !matches!(result.kind, CommandKind::Ok) {
        return Vec::new();
    }
    serde_json::from_str::<Vec<Value>>(&result.stdout).unwrap_or_default()
'''
new = r'''    // CAS-R33-CHAIN-HEALTH-INSPECT-PRIVACY: request a strict safe projection.
    // Bare `docker inspect` includes configuration secrets and mount details even
    // when the UI never renders them. Keep all unrequested fields outside Transfer.
    let projection = r#"{"Id":{{json .Id}},"Name":{{json .Name}},"State":{{json .State}},"RestartCount":{{json .RestartCount}},"Labels":{{json .Config.Labels}}}"#;
    let mut args = vec![
        "inspect".to_owned(),
        "--format".to_owned(),
        projection.to_owned(),
    ];
    args.extend(ids.iter().take(MAX_CONTAINERS).cloned());
    let result = run_command("docker", &args, Duration::from_secs(4)).await;
    if !matches!(result.kind, CommandKind::Ok) {
        return Vec::new();
    }
    result
        .stdout
        .lines()
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .collect()
'''
if old not in body:
    raise SystemExit("r33 Docker inspect function anchor missing")
body = body.replace(old, new, 1)
body = body.replace(
    '        .pointer("/Config/Labels/com.docker.compose.project")',
    '        .pointer("/Labels/com.docker.compose.project")',
)
body = body.replace(
    '        .pointer("/Config/Labels/com.docker.compose.service")',
    '        .pointer("/Labels/com.docker.compose.service")',
)
body = body.replace(
    '        .pointer("/Config/Labels/com.docker.compose.oneoff")',
    '        .pointer("/Labels/com.docker.compose.oneoff")',
)
TARGET.write_text(body, encoding="utf-8")
print("r33 Docker inspect privacy projection: COMPLETE")
