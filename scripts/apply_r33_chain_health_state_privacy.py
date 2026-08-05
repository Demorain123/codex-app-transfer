from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/chain_health.rs"
MARKER = "CAS-R33-CHAIN-HEALTH-STATE-PROJECTION"

body = TARGET.read_text(encoding="utf-8")
if MARKER in body:
    print("r33 Docker state projection already applied")
    raise SystemExit(0)

old_projection = r'''    let projection = r#"{"Id":{{json .Id}},"Name":{{json .Name}},"State":{{json .State}},"RestartCount":{{json .RestartCount}},"Labels":{{json .Config.Labels}}}"#;'''
new_projection = r'''    // CAS-R33-CHAIN-HEALTH-STATE-PROJECTION: project only scalar state fields.
    // Container state also carries historical healthcheck command output; diagnostics
    // need only the current status and must not ingest that output history.
    let projection = r#"{"Id":{{json .Id}},"Name":{{json .Name}},"Running":{{json .State.Running}},"Status":{{json .State.Status}},"HealthStatus":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},"Restarting":{{json .State.Restarting}},"OOMKilled":{{json .State.OOMKilled}},"ExitCode":{{json .State.ExitCode}},"RestartCount":{{json .RestartCount}},"Labels":{{json .Config.Labels}}}"#;'''
if old_projection not in body:
    raise SystemExit("r33 full State projection anchor missing")
body = body.replace(old_projection, new_projection, 1)

old_parse = '''        let state = value.get("State").unwrap_or(&Value::Null);
        let health = state
            .get("Health")
            .and_then(|h| h.get("Status"))
            .and_then(Value::as_str)
            .map(ToOwned::to_owned);
'''
new_parse = '''        let state = &value;
        let health = state
            .get("HealthStatus")
            .and_then(Value::as_str)
            .map(ToOwned::to_owned);
'''
if old_parse not in body:
    raise SystemExit("r33 State parser anchor missing")
body = body.replace(old_parse, new_parse, 1)

old_test = '''        assert!(is_compose_oneoff(&json!({
            "Config": {"Labels": {"com.docker.compose.oneoff": "True"}}
        })));'''
new_test = '''        assert!(is_compose_oneoff(&json!({
            "Labels": {"com.docker.compose.oneoff": "True"}
        })));'''
if old_test in body:
    body = body.replace(old_test, new_test, 1)

TARGET.write_text(body, encoding="utf-8")
print("r33 Docker scalar state projection: COMPLETE")
