from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
text = TARGET.read_text(encoding="utf-8")

old = '''        let _ = rpc.call(
            "initialize",
            json!({
                "clientInfo": {
                    "name": "codex_app_transfer_thread_recovery",
                    "title": "Codex App Transfer Thread Recovery",
                    "version": "r46"
                },
                "capabilities": { "experimentalApi": true }
            }),
        )?;
'''
new = '''        let _ = rpc
            .call(
                "initialize",
                json!({
                    "clientInfo": {
                        "name": "codex_app_transfer_thread_recovery",
                        "title": "Codex App Transfer Thread Recovery",
                        "version": "r46"
                    },
                    "capabilities": { "experimentalApi": true }
                }),
            )
            .map_err(|e| e.to_string())?;
'''
if old in text:
    text = text.replace(old, new, 1)
elif '.map_err(|e| e.to_string())?;' not in text:
    raise SystemExit("r46 recovery backend fix: initialize anchor missing")

TARGET.write_text(text, encoding="utf-8")
print("R46 THREAD RECOVERY BACKEND FIXES PASS")
