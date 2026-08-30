from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NO_MICRO = ROOT / "src-tauri/src/admin/services/desktop/no_micro.rs"
MARKER = "CAS-R49-NO-MICRO-TEMP-SCOPE-FIX"

text = NO_MICRO.read_text(encoding="utf-8")
if MARKER in text:
    print("r49 No Lagging TEMP scope fix already applied")
    raise SystemExit(0)

log_block = '''    if !custom_temp_env.is_empty() {
        tracing::info!(
            custom_temp = true,
            launcher = "no-lagging-b",
            "[r49] No Lagging launcher inherits Transfer-scoped Codex TEMP"
        );
    }
'''

# The original r49 overlay used the first generic hide_console_window(...).output()
# anchor in this file. That can be command_version()/PowerShell helper code, where
# custom_temp_env is not in scope. Remove any such log block, then put exactly one
# after the B launcher's .envs(custom_temp_env...) command construction.
text = text.replace(log_block, "")

command_anchor = '''        .envs(custom_temp_env.iter().map(|(key, value)| (key, value)))
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
'''
if command_anchor not in text:
    raise SystemExit("r49 No Lagging TEMP scope fix: B launcher envs anchor missing")

replacement = command_anchor + '''    // CAS-R49-NO-MICRO-TEMP-SCOPE-FIX
''' + log_block
text = text.replace(command_anchor, replacement, 1)

# Cheap scope invariant: definition -> envs -> log, all inside launch_windows path.
def_idx = text.find("let custom_temp_env =")
envs_idx = text.find(".envs(custom_temp_env.iter()")
log_idx = text.find('launcher = "no-lagging-b"')
launch_idx = text.find("fn launch_windows(extra_args: &[String])")
if min(def_idx, envs_idx, log_idx, launch_idx) < 0:
    raise SystemExit("r49 No Lagging TEMP scope fix: required launch markers missing")
if not (launch_idx < def_idx < envs_idx < log_idx):
    raise SystemExit("r49 No Lagging TEMP scope fix: custom TEMP markers are not in launch_windows order")
if text.count('launcher = "no-lagging-b"') != 1:
    raise SystemExit("r49 No Lagging TEMP scope fix: expected exactly one B TEMP log marker")

NO_MICRO.write_text(text, encoding="utf-8")
print("R49 NO-LAGGING TEMP SCOPE FIX PASS")
print("- removed misplaced custom_temp_env reference from helper command scope")
print("- B TEMP log now runs only after the Node launcher receives TEMP/TMP/TMPDIR")
