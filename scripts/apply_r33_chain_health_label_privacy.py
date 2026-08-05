from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
MARKER = "CAS-R33-CHAIN-HEALTH-LABEL-PROJECTION"

body = TARGET.read_text(encoding="utf-8")
if MARKER in body:
    print("r33 Compose label projection already applied")
    raise SystemExit(0)

old = r'''    let projection = r#"{"Id":{{json .Id}},"Name":{{json .Name}},"Running":{{json .State.Running}},"Status":{{json .State.Status}},"HealthStatus":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},"Restarting":{{json .State.Restarting}},"OOMKilled":{{json .State.OOMKilled}},"ExitCode":{{json .State.ExitCode}},"RestartCount":{{json .RestartCount}},"Labels":{{json .Config.Labels}}}"#;'''
new = r'''    // CAS-R33-CHAIN-HEALTH-LABEL-PROJECTION: request only the three standard
    // Compose identity labels needed for dependency grouping. Custom labels stay
    // outside Transfer because they may contain user-defined sensitive metadata.
    let projection = r#"{"Id":{{json .Id}},"Name":{{json .Name}},"Running":{{json .State.Running}},"Status":{{json .State.Status}},"HealthStatus":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},"Restarting":{{json .State.Restarting}},"OOMKilled":{{json .State.OOMKilled}},"ExitCode":{{json .State.ExitCode}},"RestartCount":{{json .RestartCount}},"ComposeProject":{{json (index .Config.Labels "com.docker.compose.project")}},"ComposeService":{{json (index .Config.Labels "com.docker.compose.service")}},"ComposeOneoff":{{json (index .Config.Labels "com.docker.compose.oneoff")}}}"#;'''
if old not in body:
    raise SystemExit("r33 broad label projection anchor missing")
body = body.replace(old, new, 1)

old_functions = '''fn compose_project_of(value: &Value) -> Option<String> {
    value
        .pointer("/Labels/com.docker.compose.project")
        .and_then(Value::as_str)
        .map(ToOwned::to_owned)
}

fn compose_service_of(value: &Value) -> Option<String> {
    value
        .pointer("/Labels/com.docker.compose.service")
        .and_then(Value::as_str)
        .map(ToOwned::to_owned)
}

fn is_compose_oneoff(value: &Value) -> bool {
    value
        .pointer("/Labels/com.docker.compose.oneoff")
        .and_then(Value::as_str)
        .map(|value| value.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
}
'''
new_functions = '''fn nonempty_string(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn compose_project_of(value: &Value) -> Option<String> {
    nonempty_string(value, "ComposeProject")
}

fn compose_service_of(value: &Value) -> Option<String> {
    nonempty_string(value, "ComposeService")
}

fn is_compose_oneoff(value: &Value) -> bool {
    value
        .get("ComposeOneoff")
        .and_then(Value::as_str)
        .map(|value| value.eq_ignore_ascii_case("true"))
        .unwrap_or(false)
}
'''
if old_functions not in body:
    raise SystemExit("r33 Compose label parser anchor missing")
body = body.replace(old_functions, new_functions, 1)

old_test = '''        assert!(is_compose_oneoff(&json!({
            "Labels": {"com.docker.compose.oneoff": "True"}
        })));'''
new_test = '''        assert!(is_compose_oneoff(&json!({"ComposeOneoff": "True"})));
        assert_eq!(
            compose_project_of(&json!({"ComposeProject": "deploy"})).as_deref(),
            Some("deploy")
        );'''
if old_test not in body:
    raise SystemExit("r33 Compose projection test anchor missing")
body = body.replace(old_test, new_test, 1)

TARGET.write_text(body, encoding="utf-8")
print("r33 Compose label projection: COMPLETE")
