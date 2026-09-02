from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
MARKER = "CAS-R61-LEGACY-COMPACTION-V1"

text = PROCESS.read_text(encoding="utf-8")
if MARKER in text:
    print("r61 legacy compaction V1 launch guard already applied")
    raise SystemExit(0)

open_anchor = 'fn open_codex_app(platform: &str) -> Result<(), String> {\n'
if open_anchor not in text:
    raise SystemExit("r61: open_codex_app anchor missing")

helper = r'''
// CAS-R61-LEGACY-COMPACTION-V1
//
// Codex remote_compaction_v2 rebuilds the post-compact history client-side by
// retaining selected prior items and appending the compaction output.  On the
// affected Windows Desktop build that can leave a multi-megabyte thread almost
// unchanged, so the next model-switch turn sees comp_hash_changed again and
// immediately compacts a second time.  Transfer already implements the legacy
// /responses/compact contract locally for the Sub2API compatibility path (r52),
// and legacy V1 installs the endpoint output as the replacement history instead
// of running the V2 retained-history builder.
//
// For the r61 compatibility build, make the official Codex feature override
// explicit in ~/.codex/config.toml before launching Codex:
//     [features]
//     remote_compaction_v2 = false
// This is the config.toml equivalent of `codex --disable remote_compaction_v2`.
// The updater is idempotent, preserves every unrelated line, never creates a
// second [features] table, and runs while Codex is closed in both normal and
// alternate (No Micro) launch pipelines.
fn sync_codex_legacy_compaction_v1_r61() {
    #[cfg(not(target_os = "windows"))]
    {
        return;
    }

    #[cfg(target_os = "windows")]
    {
        let root = std::env::var_os("CODEX_HOME")
            .filter(|value| !value.is_empty())
            .map(PathBuf::from)
            .or_else(|| codex_app_transfer_registry::paths::resolve_home().map(|home| home.join(".codex")));
        let Some(root) = root else {
            tracing::warn!("[model-switch-r61] action=disable_remote_compaction_v2 status=skip reason=codex_home_unresolved");
            return;
        };
        if let Err(error) = fs::create_dir_all(&root) {
            tracing::warn!(path = %root.display(), error = %error, "[model-switch-r61] action=disable_remote_compaction_v2 status=skip reason=create_codex_home_failed");
            return;
        }
        let path = root.join("config.toml");
        let original = match fs::read_to_string(&path) {
            Ok(value) => value,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => String::new(),
            Err(error) => {
                tracing::warn!(path = %path.display(), error = %error, "[model-switch-r61] action=disable_remote_compaction_v2 status=skip reason=read_failed");
                return;
            }
        };

        let mut output: Vec<String> = Vec::new();
        let mut in_features = false;
        let mut saw_features = false;
        let mut wrote_key = false;

        for line in original.lines() {
            let trimmed = line.trim();
            let is_table = trimmed.starts_with('[') && trimmed.ends_with(']');
            if is_table {
                if in_features && !wrote_key {
                    output.push("remote_compaction_v2 = false # CAS-R61 managed compatibility override".to_owned());
                    wrote_key = true;
                }
                in_features = trimmed == "[features]";
                saw_features |= in_features;
                output.push(line.to_owned());
                continue;
            }

            if in_features {
                let key = trimmed
                    .split_once('=')
                    .map(|(key, _)| key.trim())
                    .unwrap_or("");
                if key == "remote_compaction_v2" {
                    output.push("remote_compaction_v2 = false # CAS-R61 managed compatibility override".to_owned());
                    wrote_key = true;
                    continue;
                }
            }
            output.push(line.to_owned());
        }

        if in_features && !wrote_key {
            output.push("remote_compaction_v2 = false # CAS-R61 managed compatibility override".to_owned());
            wrote_key = true;
        }
        if !saw_features {
            if !output.is_empty() && output.last().is_some_and(|line| !line.is_empty()) {
                output.push(String::new());
            }
            output.push("[features]".to_owned());
            output.push("remote_compaction_v2 = false # CAS-R61 managed compatibility override".to_owned());
            wrote_key = true;
        }
        if !wrote_key {
            tracing::warn!(path = %path.display(), "[model-switch-r61] action=disable_remote_compaction_v2 status=skip reason=managed_key_not_materialized");
            return;
        }

        let mut updated = output.join("\n");
        updated.push('\n');
        if updated == original {
            tracing::info!(path = %path.display(), "[model-switch-r61] action=disable_remote_compaction_v2 status=already_disabled implementation=legacy_v1");
            return;
        }
        if let Err(error) = fs::write(&path, updated) {
            tracing::warn!(path = %path.display(), error = %error, "[model-switch-r61] action=disable_remote_compaction_v2 status=skip reason=write_failed");
            return;
        }
        tracing::warn!(path = %path.display(), "[model-switch-r61] action=disable_remote_compaction_v2 status=applied implementation=legacy_v1 reason=avoid_v2_retained_history_recompact_loop");
    }
}

'''
text = text.replace(open_anchor, helper + open_anchor, 1)

normal_old = '''    sync_codex_reasoning_efforts_state();

    // Windows MSIX activation:'''
normal_new = '''    sync_codex_reasoning_efforts_state();
    // CAS-R61-LEGACY-COMPACTION-V1: install the feature override while Codex is
    // still closed so this launch reads it before pre-turn compaction selection.
    sync_codex_legacy_compaction_v1_r61();

    // Windows MSIX activation:'''
if normal_old not in text:
    raise SystemExit("r61: normal launch state-sync anchor missing")
text = text.replace(normal_old, normal_new, 1)

alternate_old = '''pub fn prepare_codex_alternate_launch_args() -> Vec<String> {
    sync_codex_pet_state();
    sync_codex_reasoning_efforts_state();
    should_attach_debug_port()
}'''
alternate_new = '''pub fn prepare_codex_alternate_launch_args() -> Vec<String> {
    sync_codex_pet_state();
    sync_codex_reasoning_efforts_state();
    // Keep No Micro / alternate launcher behavior identical to the normal r61 path.
    sync_codex_legacy_compaction_v1_r61();
    should_attach_debug_port()
}'''
if alternate_old not in text:
    raise SystemExit("r61: alternate launch state-sync anchor missing")
text = text.replace(alternate_old, alternate_new, 1)

for invariant in (
    MARKER,
    "sync_codex_legacy_compaction_v1_r61",
    "remote_compaction_v2 = false # CAS-R61 managed compatibility override",
    "[model-switch-r61] action=disable_remote_compaction_v2",
    "implementation=legacy_v1",
):
    if invariant not in text:
        raise SystemExit(f"r61 process invariant missing: {invariant}")

if text.count("sync_codex_legacy_compaction_v1_r61();") != 2:
    raise SystemExit("r61 expected exactly two launch-pipeline calls (normal + alternate)")

PROCESS.write_text(text, encoding="utf-8")
print("R61 LEGACY COMPACTION V1 LAUNCH GUARD PASS")
print("- Windows Transfer launches persist features.remote_compaction_v2=false before Codex starts")
print("- normal and alternate/No-Micro launch paths are both covered")
print("- existing [features] tables are updated in place; duplicate TOML tables are not created")
print("- r60 compact transport/replay code is untouched")
