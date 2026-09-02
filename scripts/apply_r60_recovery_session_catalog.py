from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src-tauri/src/admin/handlers/thread_recovery.rs"
ADMIN = ROOT / "src-tauri/src/admin/mod.rs"
PAGE = ROOT / "frontend/src/pages/ProxyPage.vue"
API = ROOT / "frontend/src/api/threadRecovery.ts"
FRONTEND_INDEX = ROOT / "frontend/dist/index.html"

MARKER = "CAS-R60-RECOVERY-SESSION-CATALOG"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"r60 recovery session catalog: anchor missing: {label}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Backend: persistent recovery lifecycle + recent session catalog.
# This overlay is intentionally applied after r59 has materialized its
# same-thread interrupted/failed-tail recovery action.
# ---------------------------------------------------------------------------
text = BACKEND.read_text(encoding="utf-8")
if MARKER not in text:
    text = replace_once(
        text,
        "use codex_app_transfer_codex_integration::CodexPaths;\n",
        "use codex_app_transfer_codex_integration::CodexPaths;\n"
        "use codex_app_transfer_conversation_export as cexp; // CAS-R60-RECOVERY-SESSION-CATALOG\n",
        "conversation-export import",
    )
    text = replace_once(
        text,
        "use std::{\n",
        "use std::{\n    collections::HashMap,\n",
        "HashMap import",
    )

    preview_old = '''struct RecoveryPreview {
    thread_id: String,
    thread_fingerprint: String,
    rollout_path: String,
    rollout_bytes: u64,
    rollout_sha256: String,
    evidence: FailureEvidence,
    codex_cli_found: bool,
    codex_cli_path: Option<String>,
    same_thread_recovery_supported: bool,
    safeguards: Vec<String>,
}
'''
    preview_new = '''struct RecoveryPreview {
    thread_id: String,
    thread_fingerprint: String,
    rollout_path: String,
    rollout_bytes: u64,
    rollout_sha256: String,
    evidence: FailureEvidence,
    codex_cli_found: bool,
    codex_cli_path: Option<String>,
    same_thread_recovery_supported: bool,
    safeguards: Vec<String>,
    // CAS-R60-RECOVERY-SESSION-CATALOG
    // A historical failure is not permanently "current". r60 keeps a small local
    // structural receipt so a verified same-ID recovery can resolve old evidence.
    recovery_status: String,
    recovery: Option<RecoveryStatusEntry>,
}
'''
    text = replace_once(text, preview_old, preview_new, "RecoveryPreview lifecycle fields")

    insert_anchor = '''#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RecoveryActionBody {
'''
    structs = r'''// CAS-R60-RECOVERY-SESSION-CATALOG
const RECOVERY_STATUS_VERSION: u32 = 60;
const RECOVERY_CATALOG_DEFAULT_LIMIT: usize = 50;
const RECOVERY_CATALOG_MAX_LIMIT: usize = 200;
const RECOVERY_EVIDENCE_FILE_LIMIT: usize = 4;
const RECOVERY_EVIDENCE_PER_FILE_LIMIT: usize = 256;
const RECOVERY_EVIDENCE_SCAN_BYTES: u64 = 64 * 1024 * 1024;

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct RecoveryStatusEntry {
    recovered_at: String,
    action: String,
    method: String,
    source: String,
    verified: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct RecoveryStatusRegistry {
    version: u32,
    entries: HashMap<String, RecoveryStatusEntry>,
}

#[derive(Debug, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct RecoverySessionsQuery {
    limit: Option<usize>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct RecoverySessionItem {
    thread_id: String,
    thread_fingerprint: String,
    title: Option<String>,
    kind: String,
    created_at: String,
    last_modified: String,
    turn_count: usize,
    model_provider: String,
    status: String,
    latest_failure: Option<FailureEvidence>,
    recovery: Option<RecoveryStatusEntry>,
}

'''
    text = replace_once(text, insert_anchor, structs + insert_anchor, "r60 backend structs")

    preview_anchor = "pub async fn preview(Query(query): Query<RecoveryPreviewQuery>) -> impl IntoResponse {\n"
    helpers = r'''// CAS-R60-RECOVERY-SESSION-CATALOG
fn recovery_status_path() -> Option<PathBuf> {
    codex_app_transfer_registry::config_dir()
        .map(|root| root.join("thread-recovery").join("recovery-status-r60.json"))
}

fn load_recovery_status_registry() -> RecoveryStatusRegistry {
    let Some(path) = recovery_status_path() else {
        return RecoveryStatusRegistry {
            version: RECOVERY_STATUS_VERSION,
            entries: HashMap::new(),
        };
    };
    let mut registry = fs::read(&path)
        .ok()
        .and_then(|bytes| serde_json::from_slice::<RecoveryStatusRegistry>(&bytes).ok())
        .unwrap_or_default();
    if registry.version == 0 {
        registry.version = RECOVERY_STATUS_VERSION;
    }
    registry
}

fn save_recovery_status_registry(registry: &RecoveryStatusRegistry) -> Result<(), String> {
    let path = recovery_status_path().ok_or("无法解析 r60 recovery status 目录")?;
    let parent = path.parent().ok_or("r60 recovery status 路径没有父目录")?;
    fs::create_dir_all(parent).map_err(|e| format!("创建 r60 recovery status 目录失败: {e}"))?;
    let bytes = serde_json::to_vec_pretty(registry).map_err(|e| e.to_string())?;
    let tmp = path.with_extension("json.tmp");
    fs::write(&tmp, bytes).map_err(|e| format!("写 r60 recovery status 临时文件失败: {e}"))?;
    #[cfg(target_os = "windows")]
    if path.exists() {
        fs::remove_file(&path).map_err(|e| format!("替换 r60 recovery status 旧文件失败: {e}"))?;
    }
    fs::rename(&tmp, &path).map_err(|e| format!("提交 r60 recovery status 失败: {e}"))?;
    Ok(())
}

fn r60_log_field(line: &str, name: &str) -> Option<String> {
    let prefix = format!("{name}=");
    line.split_whitespace()
        .find_map(|part| part.strip_prefix(&prefix))
        .map(|value| value.trim_matches(|c: char| c == ',' || c == ';').to_owned())
}

fn r60_log_timestamp(line: &str) -> Option<String> {
    let value = line.split('\t').next()?.trim();
    if value.len() >= 19
        && value.as_bytes().get(4) == Some(&b'-')
        && value.as_bytes().get(7) == Some(&b'-')
        && value.as_bytes().get(10) == Some(&b' ')
    {
        Some(value[..19].to_owned())
    } else {
        None
    }
}

// r59 was already shipped before the lifecycle registry existed. Migrate only the
// exact success event that r59 emitted after verifying the bad tail was gone and the
// newest persisted boundary was completed. This lets an already repaired machine be
// labelled "recovered" after installing r60 without asking the user to mutate history again.
fn migrate_verified_r59_recoveries(registry: &mut RecoveryStatusRegistry) -> bool {
    let Some(dir) = proxy_log_dir() else {
        return false;
    };
    let mut files = match fs::read_dir(dir) {
        Ok(read) => read
            .flatten()
            .map(|entry| entry.path())
            .filter(|path| path.extension().and_then(|v| v.to_str()) == Some("log"))
            .collect::<Vec<_>>(),
        Err(_) => return false,
    };
    files.sort_by_key(|path| {
        fs::metadata(path)
            .and_then(|m| m.modified())
            .unwrap_or(SystemTime::UNIX_EPOCH)
    });
    if files.len() > RECOVERY_EVIDENCE_FILE_LIMIT {
        files = files.split_off(files.len() - RECOVERY_EVIDENCE_FILE_LIMIT);
    }

    let mut changed = false;
    for path in files {
        let Ok(tail) = read_tail(&path, RECOVERY_EVIDENCE_SCAN_BYTES) else {
            continue;
        };
        for line in tail.lines() {
            if !line.contains("[thread-recovery-r59]")
                || !line.contains("stage=bad_tail_removed")
                || !line.contains("same_thread=true")
                || !line.contains("verified=true")
            {
                continue;
            }
            let Some(fingerprint) = r60_log_field(line, "thread") else {
                continue;
            };
            if fingerprint.len() != 8 || !fingerprint.bytes().all(|b| b.is_ascii_hexdigit()) {
                continue;
            }
            let recovered_at = r60_log_timestamp(line)
                .unwrap_or_else(|| "1970-01-01 00:00:00".into());
            let incoming = RecoveryStatusEntry {
                recovered_at,
                action: "rewindInterruptedTail".into(),
                method: "r59-verified-log".into(),
                source: "r59_log_migration".into(),
                verified: true,
            };
            let should_replace = registry
                .entries
                .get(&fingerprint)
                .map(|old| incoming.recovered_at > old.recovered_at)
                .unwrap_or(true);
            if should_replace {
                registry.entries.insert(fingerprint, incoming);
                changed = true;
            }
        }
    }
    changed
}

fn load_recovery_status_registry_with_migration() -> RecoveryStatusRegistry {
    let mut registry = load_recovery_status_registry();
    registry.version = RECOVERY_STATUS_VERSION;
    if migrate_verified_r59_recoveries(&mut registry) {
        if let Err(error) = save_recovery_status_registry(&registry) {
            proxy_telemetry().logs.add(
                "WARN",
                format!(
                    "[thread-recovery-r60] stage=r59_status_migration_persist_failed error={} model_request=false",
                    error
                ),
            );
        } else {
            proxy_telemetry().logs.add(
                "INFO",
                "[thread-recovery-r60] stage=r59_status_migrated verified=true model_request=false",
            );
        }
    }
    registry
}

fn record_recovery_success(result: &RecoveryActionResult) -> Result<(), String> {
    if result.action != "rewindInterruptedTail" || result.source_thread_id != result.resulting_thread_id {
        return Ok(());
    }
    let fingerprint = fingerprint8(&result.source_thread_id);
    let entry = RecoveryStatusEntry {
        recovered_at: Local::now().format("%Y-%m-%d %H:%M:%S").to_string(),
        action: result.action.clone(),
        method: result.method.clone(),
        source: "r60_recovery_receipt".into(),
        verified: true,
    };
    let mut registry = load_recovery_status_registry_with_migration();
    registry.version = RECOVERY_STATUS_VERSION;
    registry.entries.insert(fingerprint.clone(), entry.clone());
    save_recovery_status_registry(&registry)?;

    // Keep a success receipt next to the pre-mutation backup as additional local
    // provenance. It contains only structural recovery metadata, never prompt/output.
    let success_path = PathBuf::from(&result.backup.directory).join("RECOVERY-SUCCESS.json");
    let success = json!({
        "version": RECOVERY_STATUS_VERSION,
        "threadFingerprint": fingerprint,
        "recoveredAt": entry.recovered_at,
        "action": entry.action,
        "method": entry.method,
        "verified": true,
        "sameThread": true,
        "workspaceFilesChanged": false,
        "modelRequest": false
    });
    fs::write(
        &success_path,
        serde_json::to_vec_pretty(&success).map_err(|e| e.to_string())?,
    )
    .map_err(|e| format!("写 RECOVERY-SUCCESS.json 失败: {e}"))?;
    Ok(())
}

fn recent_failure_evidence_by_thread() -> HashMap<String, FailureEvidence> {
    let mut out = HashMap::new();
    let Some(dir) = proxy_log_dir() else {
        return out;
    };
    let mut files = match fs::read_dir(dir) {
        Ok(read) => read
            .flatten()
            .map(|entry| entry.path())
            .filter(|path| path.extension().and_then(|v| v.to_str()) == Some("log"))
            .collect::<Vec<_>>(),
        Err(_) => return out,
    };
    files.sort_by_key(|path| {
        fs::metadata(path)
            .and_then(|m| m.modified())
            .unwrap_or(SystemTime::UNIX_EPOCH)
    });

    for path in files.into_iter().rev().take(RECOVERY_EVIDENCE_FILE_LIMIT) {
        let Ok(tail) = read_tail(&path, RECOVERY_EVIDENCE_SCAN_BYTES) else {
            continue;
        };
        let mut end = tail.len();
        for _ in 0..RECOVERY_EVIDENCE_PER_FILE_LIMIT {
            let Some(pos) = tail[..end].rfind("upstream error diag ") else {
                break;
            };
            let start = pos.saturating_sub(8 * 1024);
            if let Some((thread_id, evidence)) = parse_latest_failure(&tail[start..end]) {
                out.entry(thread_id).or_insert(evidence);
            }
            end = pos;
        }
    }
    out
}

fn failure_is_resolved(
    thread_id: &str,
    evidence: &FailureEvidence,
    registry: &RecoveryStatusRegistry,
) -> bool {
    let fingerprint = fingerprint8(thread_id);
    let Some(recovery) = registry.entries.get(&fingerprint).filter(|entry| entry.verified) else {
        return false;
    };
    match evidence.observed_at.as_deref() {
        Some(failed_at) => recovery.recovered_at.as_str() >= failed_at,
        None => false,
    }
}

fn recovery_lifecycle_status(
    thread_id: &str,
    evidence: Option<&FailureEvidence>,
    registry: &RecoveryStatusRegistry,
) -> String {
    if let Some(evidence) = evidence {
        if !failure_is_resolved(thread_id, evidence, registry) {
            return "needsRecovery".into();
        }
    }
    if registry
        .entries
        .get(&fingerprint8(thread_id))
        .is_some_and(|entry| entry.verified)
    {
        "recovered".into()
    } else {
        "normal".into()
    }
}

fn latest_unresolved_failure(
    evidence: &HashMap<String, FailureEvidence>,
    registry: &RecoveryStatusRegistry,
) -> Option<(String, FailureEvidence)> {
    evidence
        .iter()
        .filter(|(thread_id, item)| !failure_is_resolved(thread_id, item, registry))
        .max_by_key(|(_, item)| item.observed_at.clone().unwrap_or_default())
        .map(|(thread_id, item)| (thread_id.clone(), item.clone()))
}

pub async fn sessions(Query(query): Query<RecoverySessionsQuery>) -> impl IntoResponse {
    let paths = match CodexPaths::from_home_env() {
        Ok(paths) => paths,
        Err(e) => return err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
    };
    let sessions = match cexp::list_sessions(&paths.codex_home) {
        Ok(value) => value,
        Err(e) => return err(StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response(),
    };
    let registry = load_recovery_status_registry_with_migration();
    let evidence = recent_failure_evidence_by_thread();
    let limit = query
        .limit
        .unwrap_or(RECOVERY_CATALOG_DEFAULT_LIMIT)
        .clamp(1, RECOVERY_CATALOG_MAX_LIMIT);

    let mut unresolved_count = 0usize;
    let mut recovered_count = 0usize;
    let items = sessions
        .into_iter()
        .take(limit)
        .map(|session| {
            let latest_failure = evidence.get(&session.id).cloned();
            let status = recovery_lifecycle_status(&session.id, latest_failure.as_ref(), &registry);
            if status == "needsRecovery" {
                unresolved_count += 1;
            } else if status == "recovered" {
                recovered_count += 1;
            }
            let fingerprint = fingerprint8(&session.id);
            let recovery = registry.entries.get(&fingerprint).cloned();
            RecoverySessionItem {
                thread_id: session.id,
                thread_fingerprint: fingerprint,
                title: session.title,
                kind: match session.kind {
                    cexp::RolloutKind::Active => "active".into(),
                    cexp::RolloutKind::Archived => "archived".into(),
                },
                created_at: session.created_at.to_rfc3339(),
                last_modified: session.last_modified.to_rfc3339(),
                turn_count: session.turn_count,
                model_provider: session.model_provider,
                status,
                latest_failure,
                recovery,
            }
        })
        .collect::<Vec<_>>();

    Json(json!({
        "success": true,
        "sessions": items,
        "unresolvedCount": unresolved_count,
        "recoveredCount": recovered_count,
        "statusVersion": RECOVERY_STATUS_VERSION,
    }))
    .into_response()
}

'''
    text = replace_once(text, preview_anchor, helpers + preview_anchor, "r60 backend helpers/catalog")

    old_preview_start = '''pub async fn preview(Query(query): Query<RecoveryPreviewQuery>) -> impl IntoResponse {
    let evidence = latest_failure_evidence();
    let thread_id = query
        .thread_id
        .as_deref()
        .map(str::trim)
        .filter(|v| !v.is_empty())
        .map(str::to_owned)
        .or_else(|| evidence.as_ref().map(|item| item.0.clone()));
    let Some(thread_id) = thread_id else {
        return err(
            StatusCode::NOT_FOUND,
            "没有从最近代理错误中识别到可恢复的 thread id；可手动输入完整 thread id",
        )
        .into_response();
    };
'''
    new_preview_start = '''pub async fn preview(Query(query): Query<RecoveryPreviewQuery>) -> impl IntoResponse {
    // CAS-R60-RECOVERY-SESSION-CATALOG: auto-detect only unresolved failures.
    let registry = load_recovery_status_registry_with_migration();
    let evidence_by_thread = recent_failure_evidence_by_thread();
    let unresolved = latest_unresolved_failure(&evidence_by_thread, &registry);
    let thread_id = query
        .thread_id
        .as_deref()
        .map(str::trim)
        .filter(|v| !v.is_empty())
        .map(str::to_owned)
        .or_else(|| unresolved.as_ref().map(|item| item.0.clone()));
    let Some(thread_id) = thread_id else {
        return err(
            StatusCode::NOT_FOUND,
            "当前没有未处理的失败 session；可从会话列表选择任意 session 查看，或手动输入完整 thread id",
        )
        .into_response();
    };
'''
    text = replace_once(text, old_preview_start, new_preview_start, "state-aware preview start")

    old_preview_evidence = '''    let evidence = evidence
        .filter(|item| item.0 == thread_id)
        .map(|item| item.1)
        .unwrap_or_else(|| FailureEvidence {
            source: "manual_thread_id".into(),
            ..Default::default()
        });
    let preview = RecoveryPreview {
        thread_fingerprint: fingerprint8(&thread_id),
        thread_id,
'''
    new_preview_evidence = '''    let evidence = evidence_by_thread
        .get(&thread_id)
        .cloned()
        .unwrap_or_else(|| FailureEvidence {
            source: "manual_thread_id".into(),
            ..Default::default()
        });
    let thread_fingerprint = fingerprint8(&thread_id);
    let recovery_status = recovery_lifecycle_status(
        &thread_id,
        evidence_by_thread.get(&thread_id),
        &registry,
    );
    let recovery = registry.entries.get(&thread_fingerprint).cloned();
    let preview = RecoveryPreview {
        thread_fingerprint,
        thread_id,
'''
    text = replace_once(text, old_preview_evidence, new_preview_evidence, "preview evidence lifecycle")

    old_preview_tail = '''        same_thread_recovery_supported: cfg!(target_os = "windows"),
        safeguards: vec![
'''
    new_preview_tail = '''        same_thread_recovery_supported: cfg!(target_os = "windows"),
        recovery_status,
        recovery,
        safeguards: vec![
'''
    text = replace_once(text, old_preview_tail, new_preview_tail, "preview lifecycle assignment")

    # Persist a verified same-ID recovery *after* the recovery action itself succeeded.
    action_success_anchor = '''    result.codex_relaunched = relaunched;

    proxy_telemetry().logs.add(
'''
    action_success_new = '''    result.codex_relaunched = relaunched;

    // CAS-R60-RECOVERY-SESSION-CATALOG
    if result.action == "rewindInterruptedTail" && result.source_thread_id == result.resulting_thread_id {
        if let Err(error) = record_recovery_success(&result) {
            // History was already successfully repaired. Failure to persist the UI lifecycle
            // marker must not lie and turn the completed recovery into a fake mutation failure.
            proxy_telemetry().logs.add(
                "WARN",
                format!(
                    "[thread-recovery-r60] stage=recovery_status_persist_failed thread={} error={} recovery_already_succeeded=true model_request=false",
                    fingerprint8(&result.source_thread_id),
                    error,
                ),
            );
        } else {
            proxy_telemetry().logs.add(
                "INFO",
                format!(
                    "[thread-recovery-r60] stage=recovery_status_persisted thread={} lifecycle=recovered verified=true model_request=false",
                    fingerprint8(&result.source_thread_id),
                ),
            );
        }
    }

    proxy_telemetry().logs.add(
'''
    text = replace_once(text, action_success_anchor, action_success_new, "persist recovery status")

    for invariant in (
        MARKER,
        "RecoveryStatusRegistry",
        "RecoverySessionItem",
        "recovery-status-r60.json",
        "r59_log_migration",
        "stage=r59_status_migrated",
        "stage=recovery_status_persisted",
        "latest_unresolved_failure",
        "pub async fn sessions",
        '"needsRecovery"',
        '"recovered"',
        '"normal"',
        "RECOVERY-SUCCESS.json",
    ):
        if invariant not in text:
            raise SystemExit(f"r60 backend invariant missing: {invariant}")

    BACKEND.write_text(text, encoding="utf-8")
    print("R60 RECOVERY SESSION CATALOG BACKEND PASS")
else:
    print("r60 recovery session catalog backend already applied")


# ---------------------------------------------------------------------------
# Admin route.
# ---------------------------------------------------------------------------
admin = ADMIN.read_text(encoding="utf-8")
if '"/api/thread-recovery/sessions"' not in admin:
    action_route = '''        .route(
            "/api/thread-recovery/action",
            post(handlers::thread_recovery::action),
        )
'''
    sessions_route = action_route + '''        // CAS-R60-RECOVERY-SESSION-CATALOG: read-only recent session catalog + lifecycle labels.
        .route(
            "/api/thread-recovery/sessions",
            get(handlers::thread_recovery::sessions),
        )
'''
    admin = replace_once(admin, action_route, sessions_route, "r60 sessions route")
    ADMIN.write_text(admin, encoding="utf-8")
    print("R60 RECOVERY SESSION ROUTE PASS")
else:
    print("r60 recovery session route already applied")


# ---------------------------------------------------------------------------
# Frontend API types / calls.
# ---------------------------------------------------------------------------
api = API.read_text(encoding="utf-8")
if MARKER not in api:
    preview_fields = '''  sameThreadRecoverySupported: boolean
  safeguards: string[]
}
'''
    preview_fields_new = '''  sameThreadRecoverySupported: boolean
  safeguards: string[]
  // CAS-R60-RECOVERY-SESSION-CATALOG
  recoveryStatus: 'needsRecovery' | 'recovered' | 'normal'
  recovery?: ThreadRecoveryLifecycle | null
}
'''
    api = replace_once(api, preview_fields, preview_fields_new, "preview lifecycle API fields")

    marker_anchor = "export interface ThreadRecoveryBackup {\n"
    api_structs = r'''// CAS-R60-RECOVERY-SESSION-CATALOG
export interface ThreadRecoveryLifecycle {
  recoveredAt: string
  action: string
  method: string
  source: string
  verified: boolean
}

export interface ThreadRecoverySessionItem {
  threadId: string
  threadFingerprint: string
  title?: string | null
  kind: 'active' | 'archived'
  createdAt: string
  lastModified: string
  turnCount: number
  modelProvider: string
  status: 'needsRecovery' | 'recovered' | 'normal'
  latestFailure?: ThreadFailureEvidence | null
  recovery?: ThreadRecoveryLifecycle | null
}

export interface ThreadRecoverySessionCatalog {
  sessions: ThreadRecoverySessionItem[]
  unresolvedCount: number
  recoveredCount: number
  statusVersion: number
}

'''
    api = replace_once(api, marker_anchor, api_structs + marker_anchor, "r60 API catalog types")

    function_anchor = "export async function getThreadRecoveryPreview(threadId = ''): Promise<ThreadRecoveryPreview> {\n"
    session_function = r'''export async function getThreadRecoverySessions(limit = 50): Promise<ThreadRecoverySessionCatalog> {
  const bounded = Math.max(1, Math.min(200, Math.trunc(limit || 50)))
  const result = await api<{
    success: boolean
    sessions: ThreadRecoverySessionItem[]
    unresolvedCount: number
    recoveredCount: number
    statusVersion: number
  }>('GET', `/api/thread-recovery/sessions?limit=${bounded}`)
  return {
    sessions: result.sessions || [],
    unresolvedCount: result.unresolvedCount || 0,
    recoveredCount: result.recoveredCount || 0,
    statusVersion: result.statusVersion || 60,
  }
}

'''
    api = replace_once(api, function_anchor, session_function + function_anchor, "r60 API sessions call")
    API.write_text(api, encoding="utf-8")
    print("R60 RECOVERY SESSION CATALOG API PASS")
else:
    print("r60 recovery session catalog API already applied")


# ---------------------------------------------------------------------------
# Frontend UI: recent-session list + lifecycle chips.
# ---------------------------------------------------------------------------
page = PAGE.read_text(encoding="utf-8")
if MARKER not in page:
    import_old = '''import {
  getThreadRecoveryPreview,
  runThreadRecovery,
  type ThreadRecoveryPreview,
  type ThreadRecoveryResult,
} from '@/api/threadRecovery'
'''
    import_new = '''import {
  getThreadRecoveryPreview,
  getThreadRecoverySessions,
  runThreadRecovery,
  type ThreadRecoveryPreview,
  type ThreadRecoveryResult,
  type ThreadRecoverySessionItem,
} from '@/api/threadRecovery'
'''
    page = replace_once(page, import_old, import_new, "r60 frontend imports")

    state_anchor = "const threadRecoveryResult = ref<ThreadRecoveryResult | null>(null)\n"
    state_code = r'''const threadRecoveryResult = ref<ThreadRecoveryResult | null>(null)
// CAS-R60-RECOVERY-SESSION-CATALOG
const threadRecoverySessions = ref<ThreadRecoverySessionItem[]>([])
const threadRecoverySessionsLoading = ref(false)
const threadRecoveryUnresolvedCount = ref(0)
const threadRecoveryRecoveredCount = ref(0)
const threadRecoveryStatusVersion = ref(60)

function threadRecoveryStatusLabel(status: ThreadRecoverySessionItem['status']) {
  if (status === 'needsRecovery') return '待恢复'
  if (status === 'recovered') return '已恢复'
  return '普通'
}

function formatThreadRecoverySessionTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

async function loadThreadRecoverySessions() {
  if (threadRecoverySessionsLoading.value) return
  threadRecoverySessionsLoading.value = true
  try {
    const catalog = await getThreadRecoverySessions(50)
    threadRecoverySessions.value = catalog.sessions
    threadRecoveryUnresolvedCount.value = catalog.unresolvedCount
    threadRecoveryRecoveredCount.value = catalog.recoveredCount
    threadRecoveryStatusVersion.value = catalog.statusVersion
  } catch (e) {
    toast((e as Error).message || '会话列表读取失败', 'error')
  } finally {
    threadRecoverySessionsLoading.value = false
  }
}

async function selectThreadRecoverySession(item: ThreadRecoverySessionItem) {
  threadRecoveryThreadId.value = item.threadId
  await loadThreadRecoveryPreview(true)
}
'''
    page = replace_once(page, state_anchor, state_code, "r60 frontend catalog state")

    old_open = '''async function openThreadRecovery() {
  threadRecoveryOpen.value = true
  await loadThreadRecoveryPreview(false)
}
'''
    new_open = '''async function openThreadRecovery() {
  threadRecoveryOpen.value = true
  await loadThreadRecoverySessions()
  const unresolved = threadRecoverySessions.value.find((item) => item.status === 'needsRecovery')
  if (unresolved) {
    threadRecoveryThreadId.value = unresolved.threadId
    await loadThreadRecoveryPreview(true)
  } else {
    // Do not resurrect stale historical failure evidence just because the panel opened.
    // The recent-session list remains available for manual inspection.
    threadRecoveryPreview.value = null
    threadRecoveryResult.value = null
  }
}
'''
    page = replace_once(page, old_open, new_open, "state-aware panel open")

    # After any successful recovery, refresh lifecycle chips without clearing the action result.
    success_anchor = "    threadRecoveryResult.value = result\n"
    success_new = "    threadRecoveryResult.value = result\n    await loadThreadRecoverySessions()\n"
    page = replace_once(page, success_anchor, success_new, "refresh catalog after recovery")

    lookup_anchor = '''        <div class="thread-recovery-r46__lookup">
'''
    catalog_ui = r'''        <div class="thread-recovery-r60__catalog">
          <div class="thread-recovery-r60__catalog-head">
            <div>
              <strong>最近 Session</strong>
              <span>
                {{ threadRecoverySessions.length }} 条 · 待恢复 {{ threadRecoveryUnresolvedCount }} · 已恢复 {{ threadRecoveryRecoveredCount }}
              </span>
            </div>
            <button
              class="chain-health__button"
              :disabled="threadRecoverySessionsLoading"
              @click="loadThreadRecoverySessions"
            >
              <IconRefreshCw :class="{ 'is-spinning': threadRecoverySessionsLoading }" />
              刷新列表
            </button>
          </div>

          <div v-if="threadRecoverySessionsLoading" class="thread-recovery-r46__empty">正在读取最近 Session...</div>
          <div v-else-if="threadRecoverySessions.length" class="thread-recovery-r60__session-list">
            <button
              v-for="item in threadRecoverySessions"
              :key="item.threadId"
              type="button"
              class="thread-recovery-r60__session"
              :class="[
                `is-${item.status}`,
                { 'is-selected': item.threadId === threadRecoveryThreadId },
              ]"
              @click="selectThreadRecoverySession(item)"
            >
              <span class="thread-recovery-r60__status" :class="`is-${item.status}`">
                {{ threadRecoveryStatusLabel(item.status) }}
              </span>
              <span class="thread-recovery-r60__session-main">
                <strong>{{ item.title || '未命名会话' }}</strong>
                <code>{{ item.threadId }}</code>
              </span>
              <span class="thread-recovery-r60__session-meta">
                <small>{{ item.kind === 'active' ? 'Active' : 'Archived' }}</small>
                <small>{{ item.turnCount }} turns</small>
                <small>{{ formatThreadRecoverySessionTime(item.lastModified) }}</small>
              </span>
            </button>
          </div>
          <div v-else class="thread-recovery-r46__empty">没有找到可列出的 Codex Session。</div>

          <p v-if="threadRecoveryUnresolvedCount === 0 && threadRecoverySessions.length" class="thread-recovery-r60__all-clear">
            当前没有未处理失败；历史失败不会再被“自动检测最近失败”重复当成当前故障。仍可点击任一 Session 做只读预览。
          </p>
        </div>

'''
    page = replace_once(page, lookup_anchor, catalog_ui + lookup_anchor, "r60 session catalog UI")

    old_auto_button = r'''          <button
            class="chain-health__button"
            :disabled="threadRecoveryLoading"
            @click="loadThreadRecoveryPreview(false)"
          >
            自动检测最近失败
          </button>
'''
    new_auto_button = r'''          <button
            class="chain-health__button"
            :disabled="threadRecoveryLoading || threadRecoveryUnresolvedCount === 0"
            @click="loadThreadRecoveryPreview(false)"
          >
            {{ threadRecoveryUnresolvedCount > 0 ? '自动检测最近失败' : '无未处理失败' }}
          </button>
'''
    page = replace_once(page, old_auto_button, new_auto_button, "state-aware auto-detect button")

    details_anchor = '''          <details class="thread-recovery-r46__details">
'''
    lifecycle_ui = r'''          <div
            v-if="threadRecoveryPreview.recoveryStatus === 'recovered'"
            class="thread-recovery-r60__lifecycle is-recovered"
          >
            <strong>✓ 历史故障已处理</strong>
            <span v-if="threadRecoveryPreview.recovery">
              {{ formatThreadRecoverySessionTime(threadRecoveryPreview.recovery.recoveredAt) }} ·
              {{ threadRecoveryPreview.recovery.method }}
            </span>
            <span>这条旧失败证据保留用于取证，但已不再属于“未处理失败”。</span>
          </div>
          <div
            v-else-if="threadRecoveryPreview.recoveryStatus === 'needsRecovery'"
            class="thread-recovery-r60__lifecycle is-needsRecovery"
          >
            <strong>待恢复</strong>
            <span>检测到比最近成功恢复更新的失败证据；可按下方动作处理。</span>
          </div>

'''
    page = replace_once(page, details_anchor, lifecycle_ui + details_anchor, "preview lifecycle banner")

    style_anchor = "</style>"
    styles = r'''
/* CAS-R60-RECOVERY-SESSION-CATALOG */
.thread-recovery-r60__catalog {
  margin-top: 12px;
  padding: 10px;
  border: 1px solid color-mix(in srgb, currentColor 12%, transparent);
  border-radius: 10px;
  background: color-mix(in srgb, currentColor 2%, transparent);
}
.thread-recovery-r60__catalog-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}
.thread-recovery-r60__catalog-head > div {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}
.thread-recovery-r60__catalog-head span { font-size: 12px; opacity: .68; }
.thread-recovery-r60__session-list {
  display: grid;
  gap: 6px;
  margin-top: 9px;
  max-height: 300px;
  overflow: auto;
}
.thread-recovery-r60__session {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 8px 9px;
  border: 1px solid color-mix(in srgb, currentColor 10%, transparent);
  border-radius: 8px;
  background: var(--bg-primary, #fff);
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.thread-recovery-r60__session:hover,
.thread-recovery-r60__session.is-selected {
  border-color: color-mix(in srgb, #4e7fff 60%, currentColor 15%);
  background: color-mix(in srgb, #4e7fff 6%, var(--bg-primary, #fff));
}
.thread-recovery-r60__status {
  padding: 3px 7px;
  border-radius: 999px;
  font-size: 11px;
  white-space: nowrap;
  background: color-mix(in srgb, currentColor 8%, transparent);
}
.thread-recovery-r60__status.is-needsRecovery { color: #b65b00; background: color-mix(in srgb, #f59e0b 13%, transparent); }
.thread-recovery-r60__status.is-recovered { color: #268444; background: color-mix(in srgb, #22c55e 13%, transparent); }
.thread-recovery-r60__session-main { min-width: 0; display: grid; gap: 3px; }
.thread-recovery-r60__session-main strong,
.thread-recovery-r60__session-main code {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.thread-recovery-r60__session-main code { font-size: 11px; opacity: .72; }
.thread-recovery-r60__session-meta { display: grid; justify-items: end; gap: 2px; opacity: .66; font-size: 11px; }
.thread-recovery-r60__all-clear { margin: 8px 0 0; font-size: 12px; color: #268444; }
.thread-recovery-r60__lifecycle {
  margin-top: 10px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
  padding: 9px 10px;
  border-radius: 8px;
  font-size: 12px;
}
.thread-recovery-r60__lifecycle.is-recovered { background: color-mix(in srgb, #22c55e 10%, transparent); color: #267d3e; }
.thread-recovery-r60__lifecycle.is-needsRecovery { background: color-mix(in srgb, #f59e0b 10%, transparent); color: #9a5208; }
@media (max-width: 760px) {
  .thread-recovery-r60__session { grid-template-columns: auto minmax(0, 1fr); }
  .thread-recovery-r60__session-meta { grid-column: 2; justify-items: start; }
}
'''
    if style_anchor not in page:
        raise SystemExit("r60 frontend: </style> missing")
    page = page.rsplit(style_anchor, 1)[0] + styles + "\n" + style_anchor + page.rsplit(style_anchor, 1)[1]

    for invariant in (
        MARKER,
        "getThreadRecoverySessions",
        "threadRecoverySessions",
        "最近 Session",
        "待恢复",
        "已恢复",
        "无未处理失败",
        "历史故障已处理",
        "selectThreadRecoverySession",
    ):
        if invariant not in page:
            raise SystemExit(f"r60 frontend invariant missing: {invariant}")

    PAGE.write_text(page, encoding="utf-8")
    if FRONTEND_INDEX.is_file():
        FRONTEND_INDEX.unlink()
        print("r60 session catalog: invalidated stale frontend dist once")
    print("R60 RECOVERY SESSION CATALOG UI PASS")
else:
    print("r60 recovery session catalog UI already applied")

print("R60 RECOVERY SESSION CATALOG HOTFIX PASS")
print("- recent active/archived Codex sessions are listed with id/title/time and lifecycle chip")
print("- verified r59 bad-tail success logs are migrated into the persistent r60 recovery registry")
print("- future verified same-ID recoveries persist RECOVERY-SUCCESS.json + recovery-status-r60.json")
print("- auto-detect selects only unresolved failures; resolved historical evidence remains visible for forensics")
print("- a new failure newer than the recovery receipt reopens the session as needsRecovery")
