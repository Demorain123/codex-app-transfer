from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESS = ROOT / "src-tauri/src/admin/services/desktop/process.rs"
MARKER = "CAS-R64-POST-COMPACT-CONTINUATION-GUARD"

text = PROCESS.read_text(encoding="utf-8")
if MARKER in text:
    print("r64 post-compact continuation guard already applied")
    raise SystemExit(0)

if "CAS-R61-LEGACY-COMPACTION-V1" not in text:
    raise SystemExit("r64 requires the inherited r61 launch-time config guard")

open_anchor = 'fn open_codex_app(platform: &str) -> Result<(), String> {\n'
if open_anchor not in text:
    raise SystemExit("r64: open_codex_app anchor missing")

helper = r'''
// CAS-R64-POST-COMPACT-CONTINUATION-GUARD
//
// September 2026 Codex builds have an upstream regression where the experimental
// `context_management` path can finish a successful automatic compaction and then
// end the active turn instead of resuming unfinished model/tool work.  Transfer's
// r52/r53/r54/r56/r62 compact transport can already return a valid summary, so an
// HTTP retry here would be both too late and unsafe (it could duplicate tool side
// effects).  For the r64 Windows compatibility build we therefore disable only the
// experimental context-management feature at launch and leave the proven r61
// legacy-V1 + r60 replay stack unchanged.
//
// Supported config spellings are normalized without creating conflicting TOML:
//   [features] context_management = false
//   [features] context_management.experimental_mode = false
//   [features.context_management] experimental_mode = false
//
// The updater is idempotent, preserves unrelated settings, and runs while Codex is
// closed in both normal and alternate launch paths.
fn sync_codex_post_compact_continuation_guard_r64() {
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
            tracing::warn!("[compact-r64] action=disable_context_management status=skip reason=codex_home_unresolved");
            return;
        };
        if let Err(error) = fs::create_dir_all(&root) {
            tracing::warn!(path = %root.display(), error = %error, "[compact-r64] action=disable_context_management status=skip reason=create_codex_home_failed");
            return;
        }
        let path = root.join("config.toml");
        let original = match fs::read_to_string(&path) {
            Ok(value) => value,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => String::new(),
            Err(error) => {
                tracing::warn!(path = %path.display(), error = %error, "[compact-r64] action=disable_context_management status=skip reason=read_failed");
                return;
            }
        };

        let has_context_table = original
            .lines()
            .any(|line| line.trim() == "[features.context_management]");
        let mut output: Vec<String> = Vec::new();
        let mut in_features = false;
        let mut in_context_table = false;
        let mut saw_features = false;
        let mut wrote_context_setting = false;

        for line in original.lines() {
            let trimmed = line.trim();
            let is_table = trimmed.starts_with('[') && trimmed.ends_with(']');
            if is_table {
                if in_features && !wrote_context_setting && !has_context_table {
                    output.push("context_management = false # CAS-R64 managed continuation stability override".to_owned());
                    wrote_context_setting = true;
                }
                if in_context_table && !wrote_context_setting {
                    output.push("experimental_mode = false # CAS-R64 managed continuation stability override".to_owned());
                    wrote_context_setting = true;
                }
                in_features = trimmed == "[features]";
                in_context_table = trimmed == "[features.context_management]";
                saw_features |= in_features;
                output.push(line.to_owned());
                continue;
            }

            if in_features {
                let key = trimmed
                    .split_once('=')
                    .map(|(key, _)| key.trim())
                    .unwrap_or("");
                if key == "context_management" {
                    output.push("context_management = false # CAS-R64 managed continuation stability override".to_owned());
                    wrote_context_setting = true;
                    continue;
                }
                if key == "context_management.experimental_mode" {
                    output.push("context_management.experimental_mode = false # CAS-R64 managed continuation stability override".to_owned());
                    wrote_context_setting = true;
                    continue;
                }
            }

            if in_context_table {
                let key = trimmed
                    .split_once('=')
                    .map(|(key, _)| key.trim())
                    .unwrap_or("");
                if key == "experimental_mode" {
                    output.push("experimental_mode = false # CAS-R64 managed continuation stability override".to_owned());
                    wrote_context_setting = true;
                    continue;
                }
            }

            output.push(line.to_owned());
        }

        if in_context_table && !wrote_context_setting {
            output.push("experimental_mode = false # CAS-R64 managed continuation stability override".to_owned());
            wrote_context_setting = true;
        }
        if in_features && !wrote_context_setting && !has_context_table {
            output.push("context_management = false # CAS-R64 managed continuation stability override".to_owned());
            wrote_context_setting = true;
        }
        if !saw_features && !has_context_table {
            if !output.is_empty() && output.last().is_some_and(|line| !line.is_empty()) {
                output.push(String::new());
            }
            output.push("[features]".to_owned());
            output.push("context_management = false # CAS-R64 managed continuation stability override".to_owned());
            wrote_context_setting = true;
        }
        if !wrote_context_setting {
            tracing::warn!(path = %path.display(), "[compact-r64] action=disable_context_management status=skip reason=managed_key_not_materialized");
            return;
        }

        let mut updated = output.join("\n");
        updated.push('\n');
        if updated == original {
            tracing::info!(path = %path.display(), "[compact-r64] action=disable_context_management status=already_disabled reason=post_compact_continuation_stability");
            return;
        }
        if let Err(error) = fs::write(&path, updated) {
            tracing::warn!(path = %path.display(), error = %error, "[compact-r64] action=disable_context_management status=skip reason=write_failed");
            return;
        }
        tracing::warn!(path = %path.display(), "[compact-r64] action=disable_context_management status=applied reason=post_compact_continuation_stability");
    }
}

'''
text = text.replace(open_anchor, helper + open_anchor, 1)

r61_call = "    sync_codex_legacy_compaction_v1_r61();"
if text.count(r61_call) != 2:
    raise SystemExit("r64 expected exactly two inherited r61 launch-pipeline calls")
r64_call = r61_call + "\n    sync_codex_post_compact_continuation_guard_r64();"
text = text.replace(r61_call, r64_call)

for invariant in (
    MARKER,
    "sync_codex_post_compact_continuation_guard_r64",
    "context_management = false # CAS-R64 managed continuation stability override",
    "context_management.experimental_mode = false # CAS-R64 managed continuation stability override",
    "experimental_mode = false # CAS-R64 managed continuation stability override",
    "[compact-r64] action=disable_context_management",
    "post_compact_continuation_stability",
    "CAS-R61-LEGACY-COMPACTION-V1",
):
    if invariant not in text:
        raise SystemExit(f"r64 process invariant missing: {invariant}")

if text.count("sync_codex_post_compact_continuation_guard_r64();") != 2:
    raise SystemExit("r64 expected exactly two launch-pipeline calls (normal + alternate)")

PROCESS.write_text(text, encoding="utf-8")
print("R64 POST-COMPACT CONTINUATION GUARD PASS")
print("- Windows Transfer launches explicitly disable experimental context_management")
print("- boolean, dotted experimental_mode, and nested-table config spellings are handled")
print("- normal and alternate/No-Micro launch paths are both covered")
print("- r63 auth fence, r62 summary self-repair, r61 legacy V1, and r60 replay are untouched")
print("- no automatic model/tool request retry is introduced, avoiding duplicate side effects")
