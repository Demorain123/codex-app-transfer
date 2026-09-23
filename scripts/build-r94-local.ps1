param(
    [switch]$RunFocusedTests,
    [switch]$PreflightOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $PSScriptRoot
$R90Source = Join-Path $PSScriptRoot 'build-r90-local.ps1'
$R76OutputOwner = Join-Path $PSScriptRoot 'build-r76-output-ui-local.ps1'
$R89PanePatch = Join-Path $PSScriptRoot 'r89-r75-pane-runtime-patch-v4.inc.ps1'
$R94ExactTurnPatch = Join-Path $PSScriptRoot 'r94-r75-exact-turn-patch.inc.ps1'
$R94FinalObserverPatch = Join-Path $PSScriptRoot 'r94-r78-exact-turn-patch.inc.ps1'
$R94TurnOverlayJs = Join-Path $PSScriptRoot 'r94-exact-turn-overlay.js'
$R94DisabledStampJs = Join-Path $PSScriptRoot 'r94-timestamp-stamp-disabled.js'
$R93StatusFinalizer = Join-Path $PSScriptRoot 'r93-status-finalizer.ps1'
$R94ComposerStatusFinalizer = Join-Path $PSScriptRoot 'r94-composer-status-finalizer.ps1'
$R94TurnNotificationFinalizer = Join-Path $PSScriptRoot 'r94-turn-notification-finalizer.ps1'
$R94RuntimeDebugBanner = Join-Path $RepoRoot 'frontend\src\components\codex\RuntimeDebugBanner.vue'
$R94AppLayout = Join-Path $RepoRoot 'frontend\src\layout\AppLayout.vue'
$R94SettingsPage = Join-Path $RepoRoot 'frontend\src\pages\SettingsPage.vue'
$R94ProcessRs = Join-Path $RepoRoot 'src-tauri\src\admin\services\desktop\process.rs'
$R94DesktopHandlerRs = Join-Path $RepoRoot 'src-tauri\src\admin\handlers\desktop.rs'
$R94ThemeInjectorRs = Join-Path $RepoRoot 'src-tauri\src\codex_theme_injector.rs'
$R94CargoToml = Join-Path $RepoRoot 'src-tauri\Cargo.toml'
$R94CargoLock = Join-Path $RepoRoot 'Cargo.lock'
$R94ModernSelective = Join-Path $PSScriptRoot 'apply_r43_r65_selective_modern.py'
$R94R39LifecycleSelective = Join-Path $PSScriptRoot 'apply_r39_lifecycle_selective_modern.py'
$R94R39WindowsOwnerSelective = Join-Path $PSScriptRoot 'apply_r39_windows_owner_selective_modern.py'
$R94WindowsListenerNoInherit = Join-Path $PSScriptRoot 'apply_r94_windows_listener_noinherit.py'
$R94StaleExitGuardRecovery = Join-Path $PSScriptRoot 'apply_r94_stale_exit_guard_recovery.py'
$R94RecoveryExplainabilityUi = Join-Path $PSScriptRoot 'apply_r46_recovery_explainability_ui.py'
$R94ProxyHandlerRs = Join-Path $RepoRoot 'src-tauri\src\admin\handlers\proxy.rs'
$R94ChainHealthRs = Join-Path $RepoRoot 'src-tauri\src\admin\handlers\chain_health.rs'
$R941ApplyRs = Join-Path $RepoRoot 'crates\codex_integration\src\apply.rs'

$TempBuilder = Join-Path $PSScriptRoot '.build-r94-from-r90.generated.ps1'
$TempPanePatch = Join-Path $PSScriptRoot '.r94-r89-pane-runtime-patch.generated.inc.ps1'
$TempOverlayCheck = Join-Path $PSScriptRoot '.r94-overlay-syntax.generated.mjs'
$TempStampCheck = Join-Path $PSScriptRoot '.r94-stamp-syntax.generated.mjs'

foreach ($Path in @(
    $R90Source,
    $R76OutputOwner,
    $R89PanePatch,
    $R94ExactTurnPatch,
    $R94FinalObserverPatch,
    $R94TurnOverlayJs,
    $R94DisabledStampJs,
    $R93StatusFinalizer,
    $R94ComposerStatusFinalizer,
    $R94TurnNotificationFinalizer,
    $R94RuntimeDebugBanner,
    $R94AppLayout,
    $R94SettingsPage,
    $R94ProcessRs,
    $R94DesktopHandlerRs,
    $R94ThemeInjectorRs,
    $R94CargoToml,
    $R94CargoLock,
    $R94ModernSelective,
    $R94R39LifecycleSelective,
    $R94R39WindowsOwnerSelective,
    $R94WindowsListenerNoInherit,
    $R94StaleExitGuardRecovery,
    $R94RecoveryExplainabilityUi,
    $R94ProxyHandlerRs,
    $R94ChainHealthRs,
    $R941ApplyRs
)) {
    if (-not (Test-Path -LiteralPath $Path)) { throw "r94 required source missing: $Path" }
}
foreach ($Path in @($TempBuilder,$TempPanePatch,$TempOverlayCheck,$TempStampCheck)) {
    if (Test-Path -LiteralPath $Path) { throw "r94 refuses pre-existing temp path: $Path" }
}

$Utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function Normalize-Eol([string]$Text) {
    return $Text.Replace("`r`n","`n").Replace("`r","`n")
}

function Write-Utf8NoBom([string]$Path,[string]$Text) {
    [System.IO.File]::WriteAllText($Path,$Text,$Utf8NoBom)
}

function Replace-Required([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    $TextN = Normalize-Eol $Text
    $OldN = Normalize-Eol $Old
    $NewN = Normalize-Eol $New
    if (-not $TextN.Contains($OldN)) { throw "r94 expected text missing: $Label" }
    return $TextN.Replace($OldN,$NewN)
}

function Assert-PowerShellParses([string]$Text,[string]$Label) {
    $Tokens = $null
    $Errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput($Text,[ref]$Tokens,[ref]$Errors)
    if ($Errors -and $Errors.Count -gt 0) {
        $Summary = @($Errors | Select-Object -First 8 | ForEach-Object { $_.Message }) -join ' | '
        throw "r94 PowerShell parse failed: $Label :: $Summary"
    }
}

$Dirty = @(git -C $RepoRoot status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw 'r94 git status failed' }
if ($Dirty.Count -gt 0) { throw "r94 requires a clean tracked worktree:`n$($Dirty -join "`n")" }

$Builder = Normalize-Eol ([System.IO.File]::ReadAllText($R90Source))
$R76OutputOwnerText = Normalize-Eol ([System.IO.File]::ReadAllText($R76OutputOwner))
$PanePatch = Normalize-Eol ([System.IO.File]::ReadAllText($R89PanePatch))
$ExactOverlayPatch = Normalize-Eol ([System.IO.File]::ReadAllText($R94ExactTurnPatch))
$FinalObserverPatch = Normalize-Eol ([System.IO.File]::ReadAllText($R94FinalObserverPatch))
$OverlayJs = Normalize-Eol ([System.IO.File]::ReadAllText($R94TurnOverlayJs))
$DisabledStampJs = Normalize-Eol ([System.IO.File]::ReadAllText($R94DisabledStampJs))
$StatusFinalizer = Normalize-Eol ([System.IO.File]::ReadAllText($R93StatusFinalizer))
$ComposerStatusFinalizer = Normalize-Eol ([System.IO.File]::ReadAllText($R94ComposerStatusFinalizer))
$TurnNotificationFinalizer = Normalize-Eol ([System.IO.File]::ReadAllText($R94TurnNotificationFinalizer))
$RuntimeDebugBannerText = Normalize-Eol ([System.IO.File]::ReadAllText($R94RuntimeDebugBanner))
$AppLayoutText = Normalize-Eol ([System.IO.File]::ReadAllText($R94AppLayout))
$SettingsPageText = Normalize-Eol ([System.IO.File]::ReadAllText($R94SettingsPage))
$ProcessRsText = Normalize-Eol ([System.IO.File]::ReadAllText($R94ProcessRs))
$DesktopHandlerRsText = Normalize-Eol ([System.IO.File]::ReadAllText($R94DesktopHandlerRs))
$ThemeInjectorRsText = Normalize-Eol ([System.IO.File]::ReadAllText($R94ThemeInjectorRs))
$CargoTomlText = Normalize-Eol ([System.IO.File]::ReadAllText($R94CargoToml))
$CargoLockText = Normalize-Eol ([System.IO.File]::ReadAllText($R94CargoLock))
$ModernSelectiveText = Normalize-Eol ([System.IO.File]::ReadAllText($R94ModernSelective))
$R39LifecycleSelectiveText = Normalize-Eol ([System.IO.File]::ReadAllText($R94R39LifecycleSelective))
$R39WindowsOwnerSelectiveText = Normalize-Eol ([System.IO.File]::ReadAllText($R94R39WindowsOwnerSelective))
$R94WindowsListenerNoInheritText = Normalize-Eol ([System.IO.File]::ReadAllText($R94WindowsListenerNoInherit))
$R94StaleExitGuardRecoveryText = Normalize-Eol ([System.IO.File]::ReadAllText($R94StaleExitGuardRecovery))
$R94RecoveryExplainabilityUiText = Normalize-Eol ([System.IO.File]::ReadAllText($R94RecoveryExplainabilityUi))
$ProxyHandlerText = Normalize-Eol ([System.IO.File]::ReadAllText($R94ProxyHandlerRs))
$ChainHealthText = Normalize-Eol ([System.IO.File]::ReadAllText($R94ChainHealthRs))
$R941ApplyRsText = Normalize-Eol ([System.IO.File]::ReadAllText($R941ApplyRs))

foreach ($Marker in @(
    'apply_r39_lifecycle_selective_modern.py',
    'R82_R39_LIFECYCLE_SELECTIVE_CARRY_FORWARD_PASS'
)) {
    if (-not $ModernSelectiveText.Contains($Marker)) {
        throw "r94 modern selective carry-forward source missing: $Marker"
    }
}
if (-not $R39LifecycleSelectiveText.Contains('apply_r39_windows_owner_selective_modern.py')) {
    throw 'r94 r39 lifecycle selective source must use the modern Windows-owner substrate leaf'
}
if (-not $R39LifecycleSelectiveText.Contains('apply_r94_windows_listener_noinherit.py')) {
    throw 'r94 r39 lifecycle selective source must install the fixed-port listener no-inherit guard'
}
foreach ($Marker in @(
    'CAS-R94-WINDOWS-LISTENER-NOINHERIT',
    'SetHandleInformation',
    'GetHandleInformation',
    'HANDLE_FLAG_INHERIT',
    'listener_inherit_guard_verified',
    'inheritable=false'
)) {
    if (-not $R94WindowsListenerNoInheritText.Contains($Marker)) {
        throw "r94 Windows listener no-inherit source missing: $Marker"
    }
}
if (-not $R94WindowsListenerNoInheritText.Contains('SetHandleInformation(handle, HANDLE_FLAG_INHERIT.0, HANDLE_FLAGS(0))')) {
    throw 'r94 Windows listener guard must explicitly clear HANDLE_FLAG_INHERIT'
}
if ($R94WindowsListenerNoInheritText.Contains('SO_REUSEADDR') -and
    -not $R94WindowsListenerNoInheritText.Contains('no SO_REUSEADDR workaround')) {
    throw 'r94 Windows listener guard must not use SO_REUSEADDR'
}
if ($R39LifecycleSelectiveText.Contains('run_leaf("scripts/apply_r38_windows_port_owner.py")')) {
    throw 'r94 r39 lifecycle selective source regressed to the historical r38 proxy-runner-coupled owner leaf'
}
foreach ($Marker in @(
    'CAS-R94-STALE-EXIT-GUARD-RECOVERY',
    'CAS-R39-BINDER-TERMINOLOGY',
    'classification=unresolved_listener_residue',
    'match_start_token',
    'match_next_token',
    'recommend_start',
    'recommend_next',
    'recommend_start = text.find(''        "transfer_port_stale_owner" =>'', recommend_scope)',
    'recommend_next = text.find(''        "transfer_stopped" =>'', recommend_start)',
    'preserve_stale_listener_evidence',
    'recover_stale_exit_guard_listener_r94',
    'r94_find_stale_exit_guard_child',
    'r94_stop_exact_stale_exit_guard',
    'preserve_running_codex_exit_guard',
    'stale_listener_identity_changed',
    'fixed_port_released',
    'mcp-exit-guard-r32.ps1',
    '$targetPid={guard_pid}',
    'concat!(',
    'dead_binder_pid = dead_binder_pid',
    'guard_pid = guard_pid',
    '保持原端口不变'
)) {
    if (-not $R94StaleExitGuardRecoveryText.Contains($Marker)) {
        throw "r94 stale Exit Guard repair source missing: $Marker"
    }
}
foreach ($Forbidden in @(
    'taskkill /T',
    'taskkill /IM',
    'Stop-Process -Name',
    'Get-Process | Stop-Process',
    '$pid={guard_pid}'
)) {
    if ($R94StaleExitGuardRecoveryText.Contains($Forbidden)) {
        throw "r94 stale Exit Guard repair source contains forbidden broad cleanup: $Forbidden"
    }
}
foreach ($Marker in @(
    "h.transfer.code === 'transfer_port_stale_owner'",
    "title: '适用：旧 Transfer 的 Exit Guard 残留占用固定端口'",
    "不会换端口",
    "h.transfer.code === 'transfer_port_occupied_live'"
)) {
    if (-not $R94RecoveryExplainabilityUiText.Contains($Marker)) {
        throw "r94 stale-listener repair UI source missing: $Marker"
    }
}
if (-not $ModernSelectiveText.Contains('scripts/apply_r94_stale_exit_guard_recovery.py')) {
    throw 'r94 modern selective materializer does not include stale Exit Guard repair leaf'
}
foreach ($Marker in @(
    'MODERN-R39-WINDOWS-OWNER-SELECTIVE',
    'MODERN_R39_WINDOWS_OWNER_SELECTIVE_PASS',
    'GetExtendedTcpTable',
    'TCP_TABLE_OWNER_PID_LISTENER'
)) {
    if (-not $R39WindowsOwnerSelectiveText.Contains($Marker)) {
        throw "r94 modern Windows owner source missing: $Marker"
    }
}
if ($R39WindowsOwnerSelectiveText.Contains('PATH = ROOT / "src-tauri/src/proxy_runner.rs"')) {
    throw 'r94 modern Windows owner substrate must not patch proxy_runner.rs'
}
foreach ($Marker in @(
    'const RETRY_MS: &[u64] = &[50, 100, 200, 400, 800];',
    '[proxy-lifecycle-r28] bind busy requested_port='
)) {
    if (-not $ProxyHandlerText.Contains($Marker)) {
        throw "r94 r39 bind-policy baseline anchor missing: $Marker"
    }
}
foreach ($Marker in @(
    'let proxy_status = state.proxy_manager.status();',
    'fn recovery_classification(snapshot: &ChainHealthSnapshot)',
    'state.proxy_manager.stop_silent();'
)) {
    if (-not $ChainHealthText.Contains($Marker)) {
        throw "r94 r39 recovery-classification baseline anchor missing: $Marker"
    }
}
Write-Host 'R94_R39_LIFECYCLE_SOURCE_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host '  - Windows owner substrate is decoupled from historical r38 proxy_runner anchors'
Write-Host '  - fixed-port listener handle inheritance is explicitly blocked and read-back verified'
Write-Host '  - current r28 bind/recovery anchors required by the selective r39 upgrade are present'
Write-Host 'R94_WINDOWS_LISTENER_NOINHERIT_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host 'R94_STALE_EXIT_GUARD_TRY_REPAIR_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host '  - repair leaf targets the r39 binder-terminology owner via semantic branch boundaries'
Write-Host '  - Rust format!(concat!(...)) placeholders use explicit named arguments'
Write-Host '  - dead binder is verified twice before any process action'
Write-Host '  - only one exact direct-child r32 Exit Guard may be stopped after identity re-check'
Write-Host '  - configured fixed port is preserved; live owners and ambiguous candidates fail closed'

foreach ($Marker in @(
    'R94_EXACT_TIMESTAMP_OVERLAY_RUNTIME',
    'R94_EXACT_TURN_CAPABILITY_RUNTIME',
    'R94_NATIVE_TIMESTAMP_VISIBILITY_GATE_RUNTIME',
    'R94_NATIVE_TIMESTAMP_ANCESTOR_VISIBILITY_RUNTIME',
    'r94NativeTimestampVisible(exact.sourceElement)',
    'window.__casR94TurnCapability = capability;',
    'function r94CreateCapability() {',
    'function latestForThread(threadId) {',
    'const latestKeyByThread = new Map();',
    'capabilitySequence',
    'usageFingerprint',
    'lifecycleFingerprint',
    'function r94NativeExactForTurn(turn) {',
    '[data-content-search-assistant-turn-key]',
    '[data-chatgpt-conversation-turn="true"]',
    'function r94NativeTimestampVisible(node) {',
    'function r94NativeUserExactForTurn(turn) {',
    'function r94EnsureUserBadge(turn, ids) {'
    'R94_LIVE_SEGMENT_TIMESTAMP_RUNTIME',
    'R94_FULL_DATE_TIMESTAMP_RUNTIME',
    'R94_USER_PROMPT_TIMESTAMP_RUNTIME',
    'function r94LocalDateTimeStamp(epoch) {',
    'R94_NATIVE_RAIL_PRESERVE_RUNTIME',
    'R94_NATIVE_RAIL_METADATA_ONLY_RUNTIME',
    'R94_NATIVE_RAIL_NO_CUSTOM_PAINT_RUNTIME',
    'const timelineRail = null;',
    'function r94UpsertTimelineEntry(key, epoch, anchor, kind, approx, preview) {',
    'R94_STREAMING_SEGMENT_THROTTLE_RUNTIME',
    'R94_STREAMING_LATEST_OWNER_CACHE_RUNTIME',
    'R94_MULTI_PANE_THREAD_OWNERSHIP_RUNTIME',
    'R94_MULTI_PANE_LATEST_OWNER_CACHE_RUNTIME',
    'function r94RememberLatestObservedTurn(turn) {',
    'latestObservedTurn = turn;',
    'R94_MULTI_PANE_FAIL_CLOSED_RUNTIME',
    'function r94ThreadIdForNode(node) {',
    'const latestObservedTurnByThread = new Map();',
    'R94_NO_VIEWPORT_EDGE_PINNING_RUNTIME',
    'window.setTimeout(r94FlushSegmentTurns, 220)',
    'R94_SEMANTIC_OUTPUT_UNIT_RUNTIME',
    'R94_STRUCTURAL_STATUS_FALLBACK_RUNTIME',
    'function r94FallbackSemanticSignature(node) {',
    'function r94FallbackSemanticOutputSurfaces(turn) {',
    'R94_ASSISTANT_PROSE_WITH_TOOL_RUNTIME',
    'function r94AssistantWrapperHasOwnProse(node) {',
    'R94_ITEM_ID_DEDUPE_SPECIFICITY_RUNTIME',
    'function r94DirectItemIdForSurface(surface) {',
    'function r94CollectSemanticOutputSurfaces(turn) {',
    'R94_NO_DESCENDANT_EXACT_BORROW_RUNTIME',
    'R94_PANE_TPS_SAMPLE_CLOCK_RUNTIME',
    'R94_NATIVE_TIME_FULL_FORMAT_OVERLAY_RUNTIME',
    "mode: 'native-time-cover'",
    'function r94ExactItemTimeForSurface(surface, turn, capability) {',
    'function r94ItemIdForSurface(surface) {',
    'function r94AssistantMessageSurface(node) {',
    'function r94IsUserSurface(node) {',
    'function r94HostEpochNow() {',
    'const systemEpoch = new Date().getTime();',
    'R94_ITEM_EXACT_TIMESTAMP_RUNTIME',
    "method === 'item/started'",
    "method === 'item/completed'",
    'r94BaselineCurrentSegments();',
    'r94SuppressNativeFinalSegmentBadge(turn);',
    'new IntersectionObserver(function(entries) {',
    'mutationObserver.observe(document.documentElement, { childList: true, subtree: true });',
    'state.observer = { disconnect: r94Cleanup };'
)) {
    if (-not $OverlayJs.Contains($Marker)) { throw "r94 turn overlay contract missing: $Marker" }
}
if ($OverlayJs -match 'function r94RememberLatestObservedTurn\(turn\)[\s\S]{0,220}r94RememberLatestObservedTurn\(turn\);') {
    throw 'r94 latest-owner helper regressed to self recursion'
}
Write-Host 'R94_LATEST_OWNER_HELPER_NONRECURSIVE_PASS' -ForegroundColor Green

foreach ($Forbidden in @(
    'characterData: true',
    'characterData:true',
    'Date.now()',
    'segment.insertBefore(',
    'segment.appendChild(',
    'actionRow.insertAdjacentElement(',
    'first observed live output',
    'first observed output',
    'setInterval('
)) {
    if ($OverlayJs.Contains($Forbidden)) { throw "r94 turn overlay retained forbidden hot path: $Forbidden" }
}
Write-Host 'R94_PER_OUTPUT_TIMESTAMP_CONTRACT_PASS' -ForegroundColor Green
Write-Host '  - nested assistant message groups are timestamp units; explicit tool/agent/status surfaces remain independent'
Write-Host '  - assistant prose surrounding embedded tool/agent/status cards keeps its own timestamp unit'
Write-Host '  - current Codex agent/progress cards without stable test ids use a bounded structural status fallback'
Write-Host '  - nested wrapper item ids cannot steal the concrete tool/agent item timestamp'
Write-Host '  - prose-bearing assistant wrappers never borrow an embedded tool item exact time'
Write-Host '  - user-only wrappers are excluded from assistant timestamping'
Write-Host '  - existing/remounted history is baselined and cannot receive a fresh host-now timestamp'
Write-Host '  - native final sent-time remains read-only; short native labels are visually covered by one full-date overlay only when an exact epoch exists'
Write-Host '  - all Transfer timestamp badges live in the overlay root with pointer-events:none'
Write-Host 'R94_FULL_DATE_TIMESTAMP_CONTRACT_PASS' -ForegroundColor Green
Write-Host '  - Transfer-owned timestamp labels use the current host system wall clock as YYYY-MM-DD HH:mm:ss; tooltip also carries the short local timezone'
Write-Host '  - ambiguous native time-only history is never assigned a guessed date'
if ($OverlayJs.Contains('const timelineRail = r94EnsureTimelineRailRoot();') -or
    $OverlayJs.Contains('r94CreateTimelineMarker(timelineRail, entry)')) {
    throw 'r94 custom timeline rail paint path survived; Codex native rail must remain untouched'
}
Write-Host 'R94_NATIVE_RAIL_NO_CUSTOM_DOM_PASS' -ForegroundColor Green
Write-Host 'R94_NATIVE_RAIL_PRESERVE_CONTRACT_PASS' -ForegroundColor Green
Write-Host '  - Codex official conversation rail/minimap remains the only visible navigation rail'
Write-Host '  - Transfer keeps bounded timestamp metadata only; it creates no custom rail/tick/marker DOM'
Write-Host '  - per-output timestamp badges stay in the separate pointer-events:none overlay'
Write-Host '  - streaming timestamp scans are throttled and reuse cached active-turn/composer ownership'
foreach ($Marker in @(
    'R94_EXACT_TIMESTAMP_OVERLAY_GENERATION_PATCH',
    'R94_FINAL_TIMESTAMP_OWNERS_REPLACED_PASS',
    'R94_PANE_RUNTIME_PRESERVED_ACROSS_EXACT_OWNER_PASS',
    'R94_R86_STRICT_TIMESTAMP_VERIFIER_SUPERSEDED_PASS',
    'R94_FINAL_R78_OBSERVER_PATCH_INSTALLED_PASS',
    'R94_R78_EXACT_OVERLAY_FINAL_OWNER_PASS',
    'R94_R77_TIMESTAMP_ROOT_COMPAT_SUPERSEDED_PASS',
    'R94_R77_TIMESTAMP_RECOVERY_SUPERSEDED_PASS',
    'R94_R77_TELEMETRY_PRESERVED_TIMESTAMP_SUPERSEDED_PASS',
    'R94_R77_MODEL_COLLECTOR_COMPAT_SOURCE_PASS',
    'R94_R77_BOUNDED_MODEL_LOOKUP_SUPERSEDED_PASS',
    'R94_R77_ACTIVE_THREAD_RESOLVER_COMPAT_SOURCE_PASS',
    'R94_R77_ACTIVE_THREAD_RESOLVER_SUPERSEDED_PASS',
    'R94_COMPOSER_STATUS_INSIDE_FINALIZER_BOUND_TO_R75_PASS',
    "'.r94-timestamp-observer.generated.js'",
    'R94_FINAL_TIMESTAMP_MATERIALIZATION_PREFLIGHT_PASS',
    'R94_NATIVE_REACT_DOM_READONLY_PASS'
)) {
    if (-not $ExactOverlayPatch.Contains($Marker)) { throw "r94 owner patch contract missing: $Marker" }
}
if ($ExactOverlayPatch.Contains('R94_STATUS_OVERLAY_FINALIZER_BOUND_TO_R75_PASS')) {
    throw 'r94 exact owner patch retained stale detached-status binding marker'
}
if (-not $DisabledStampJs.Contains('R94_LEGACY_TIMESTAMP_STAMP_DISABLED')) {
    throw 'r94 disabled stamp marker missing'
}
foreach ($Marker in @(
    'R94_R78_EXACT_OVERLAY_FINAL_OWNER',
    'R94_R78_EXACT_OVERLAY_FINAL_OWNER_PASS',
    'R94_COMPOSER_STATUS_INSIDE_FINALIZER_BOUND_TO_R75_PASS',
    'R94_TURN_NOTIFICATION_FINALIZER_BOUND_TO_R75_PASS',
    'r94 exact-only timestamp overlay final owner',
    'r94 live-only timestamp observer'
)) {
    if (-not $FinalObserverPatch.Contains($Marker)) { throw "r94 final observer patch contract missing: $Marker" }
}
foreach ($Marker in @(
    'r94 live-only timestamp observer',
    'R94_TIMESTAMP_ACTIONROW_V4_PASS'
)) {
    if (-not $DisabledStampJs.Contains($Marker)) { throw "r94 disabled stamp compatibility sentinel missing: $Marker" }
}
Write-Host 'R94_RETARGETED_R86_VERIFIER_COMPAT_PREFLIGHT_PASS' -ForegroundColor Green
Assert-PowerShellParses $FinalObserverPatch 'r94 final r78 observer patch include'
Write-Host 'R94_FINAL_R78_OBSERVER_PATCH_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host 'R94_EXACT_TURN_PREFLIGHT_CONTRACT_PASS' -ForegroundColor Green
foreach ($Marker in @(
    'R93_COMPOSER_STATUS_STABILITY_FINALIZER',
    'R93_COMPOSER_STATUS_FINAL_OWNER_PASS',
    'R93_NATIVE_USAGE_ISOLATION_PASS',
    'R93_STATUS_RENDER_FINGERPRINT_PASS'
)) {
    if (-not $StatusFinalizer.Contains($Marker)) { throw "r93 status finalizer contract missing: $Marker" }
}
Assert-PowerShellParses $StatusFinalizer 'r93 status finalizer'
foreach ($Marker in @(
    'function r93MountStatusBar(bar, composer) {',
    'surface.insertBefore(bar, inputWrap);',
    "bar.setAttribute('data-cas-status-inside-composer','true');"
)) {
    if (-not $StatusFinalizer.Contains($Marker)) { throw "r94 inherited inside-composer mount missing: $Marker" }
}
Write-Host 'R93_STATUS_FINALIZER_PREFLIGHT_PASS' -ForegroundColor Green
foreach ($Marker in @(
    'R94_COMPOSER_STATUS_INSIDE_FINALIZER',
    'R94_STATUS_INSIDE_COMPOSER_FINAL_OWNER_PASS',
    'R94_COMPOSER_INLINE_MOUNT_V4_FAST_SAFE_PASS',
    'R94_STATUS_NEVER_ENTERS_EDITABLE_PASS',
    'R94_RESIDUAL_UNSAFE_MOUNT_REWRITE_PASS',
    'R94_UNSAFE_EDITOR_MOUNT_FALLBACKS_ABSENT_PASS',
    'R94_NATIVE_USAGE_SCAN_DISABLED_PASS',
    'R94_NO_STATUS_VIEWPORT_TRACKING_PASS',
    'R94_DUPLICATE_USAGE_MIRROR_DISABLED_PASS',
    'R94_COMPOSER_SURFACE_COMPAT_RUNTIME',
    'R94_PANE_SCOPED_STATUS_MOUNT_RUNTIME',
    'function r94EditableForComposerScope(composer) {',
    'R94_CURRENT_COMPOSER_ROOT_RUNTIME',
    'R94_COMPOSER_INLINE_MOUNT_RUNTIME',
    'R94_COMPOSER_MOUNT_V4',
    'R94_EDITOR_BOUNDARY_GUARD_RUNTIME',
    'R94_COMPOSER_FAIL_CLOSED_MOUNT_RUNTIME',
    "bar.setAttribute('data-cas-status-owner','r94-inline-safe');",
    "bar.setAttribute('contenteditable','false');",
    'function r94SafeComposerSurface(editable) {',
    '[data-testid*="composer"]',
    'R94_NATIVE_USAGE_SCAN_DISABLED_RUNTIME',
    'R94_DUPLICATE_USAGE_MIRROR_DISABLED_RUNTIME'
)) {
    if (-not $ComposerStatusFinalizer.Contains($Marker)) { throw "r94 composer status finalizer contract missing: $Marker" }
}
foreach ($Marker in @(
    'r94 refuses detached status overlay runtime:',
    'r94 detached status overlay survived final materialization:'
)) {
    if (-not $ComposerStatusFinalizer.Contains($Marker)) {
        throw "r94 composer status finalizer runtime rejection guard missing: $Marker"
    }
}
# Do not scan the finalizer SOURCE for the forbidden overlay strings here:
# they intentionally appear as literals inside its runtime fail-closed guard.
# The finalizer applies those checks to generated $Patched JavaScript instead.
$CrossPaneEditableFallback = @'
    const scopedEditable = r94VisibleComposerEditable(composer instanceof Element ? composer : null);
    const editable = scopedEditable || r94VisibleComposerEditable(null);
'@
if ($ComposerStatusFinalizer.Contains($CrossPaneEditableFallback)) {
    throw 'r94 pane-scoped status mount regressed to document-global editable fallback'
}
Write-Host 'R94_PANE_SCOPED_STATUS_MOUNT_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host 'R94_COMPOSER_STATUS_INSIDE_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host 'R94_EDITOR_SAFE_STATUS_CONTRACT_PASS' -ForegroundColor Green
Write-Host '  - status mount host must be outside ProseMirror/contenteditable and structurally tied to composer controls'
Write-Host '  - failed/unknown mount discovery removes the bar and retries later; it never falls back into the draft'
Write-Host '  - pane-specific remounts fail closed instead of borrowing another visible pane editor'
Write-Host '  - runtime Debug MATCH requires an r94-inline-safe bar and editorLeak=0'
foreach ($Marker in @(
    'R94_TURN_NOTIFICATION_FINALIZER',
    'R94_MULTI_PANE_USAGE_OWNERSHIP_RUNTIME',
    'R94_MULTI_PANE_THREAD_FALLBACK_FAIL_CLOSED_RUNTIME',
    'R94_MULTI_PANE_USAGE_OWNERSHIP_PASS',
    'r94ExternalExactByThread',
    'r94StoreExternalExact(exact);',
    'R94_LOCAL_ITEM_LIFECYCLE_BRIDGE_RUNTIME',
    'R94_LOCAL_ITEM_LIFECYCLE_BRIDGE_PASS',
    'R94_PASSIVE_ITEM_LIFECYCLE_INGEST_PASS',
    'R94_PASSIVE_TURN_NOTIFICATION_INGEST_PASS',
    'R94_LOCAL_ROLLOUT_TURN_BRIDGE_PASS',
    'R94_TURN_SCOPED_STATUS_PASS',
    'R94_TURN_NOTIFICATION_BRIDGE_RUNTIME',
    'R94_NATIVE_ACTIVE_SINGLE_PANE_FALLBACK_RUNTIME',
    'R94_EXACT_USAGE_DIRECT_DECODE_RUNTIME',
    'R94_EXACT_USAGE_INGEST_EXPORT_RUNTIME',
    'R94_STATUS_TRUTH_SEMANTICS_RUNTIME',
    'R94_NO_NATIVE_GLOBAL_SPEED_AS_PANE_SPEED_RUNTIME',
    'R94_PANE_LOCAL_TPS_RUNTIME',
    'function r94PaneSpeedPresentation(threadId, turnRecord, turnExact, activity) {',
    'exact-pane-output-delta',
    'R94_MULTI_PANE_LAST_THREAD_SNAPSHOT_FALLBACK_RUNTIME',
    'thread-snapshot-before-turn-usage',
    'exact-thread-snapshot-before-turn-usage',
    'R94_TELEMETRY_TRUTH_SEMANTICS_PASS',
    'state.ingestExternalUsage = ingestExternalUsage',
    'contextTokens',
    "('session ' + shortNumber(displayUsage.sessionTotalTokens))",
    'native-active-single-pane',
    'r94NormalizePaneId',
    'R94_TURN_STATUS_PANE_OWNER_PASS',
    'R94_PANE_STATUS_OWNER_REQUIRED',
    'refusing base-only status downgrade',
    'exact-turn-capability'
)) {
    if (-not $TurnNotificationFinalizer.Contains($Marker)) { throw "r94 notification finalizer contract missing: $Marker" }
}
if (-not $TurnNotificationFinalizer.Contains("'r94 multi-pane thread fallback fail-closed'")) {
    throw 'r94 split-pane thread fallback replacement guard missing from finalizer'
}
Write-Host 'R94_MULTI_PANE_THREAD_FALLBACK_FAIL_CLOSED_PREFLIGHT_PASS' -ForegroundColor Green
foreach ($Forbidden in @(
    'R94_TURN_STATUS_BASE_OWNER_PASS',
    'R94_TURN_STATUS_BASE_OWNER_RUNTIME'
)) {
    if ($TurnNotificationFinalizer.Contains($Forbidden)) {
        throw "r94 turn finalizer still permits base-status downgrade: $Forbidden"
    }
}
Assert-PowerShellParses $ComposerStatusFinalizer 'r94 composer status finalizer'
Assert-PowerShellParses $TurnNotificationFinalizer 'r94 turn notification finalizer'
Write-Host 'R94_STATUS_AND_TURN_FINALIZERS_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host '  - finalizer itself rejects misleading native/global tok/s pane attribution and input-only context math after materialization'

$RuntimeDebugContracts = @(
    @{ Text = $RuntimeDebugBannerText; Marker = 'CAS-R94-RUNTIME-DEBUG-BANNER-V1' },
    @{ Text = $RuntimeDebugBannerText; Marker = 'DBG94.1-1' },
    @{ Text = $RuntimeDebugBannerText; Marker = "EXPECTED_TRANSFER_REVISION = 'r94.1'" },
    @{ Text = $RuntimeDebugBannerText; Marker = "EXPECTED_TRANSFER_VERSION = '2.4.5+94.1'" },
    @{ Text = $RuntimeDebugBannerText; Marker = 'runtimeDebugMode' },
    @{ Text = $AppLayoutText; Marker = 'RuntimeDebugBanner' },
    @{ Text = $SettingsPageText; Marker = "toggle('runtimeDebugMode', false)" },
    @{ Text = $ProcessRsText; Marker = 'CAS-R94-RUNTIME-DEBUG-CDP-GATE' },
    @{ Text = $ProcessRsText; Marker = 'runtime_debug_enabled' },
    @{ Text = $DesktopHandlerRsText; Marker = 'CAS-R94-RUNTIME-DEBUG-REINJECT' },
    @{ Text = $DesktopHandlerRsText; Marker = 'reinject_after_codex_restart_with_mode' },
    @{ Text = $ThemeInjectorRsText; Marker = 'CAS-R94-RUNTIME-DEBUG-IDENTITY' },
    @{ Text = $ThemeInjectorRsText; Marker = 'RUNTIME_DEBUG_PROTOCOL' },
    @{ Text = $ThemeInjectorRsText; Marker = 'apply_runtime_debug_banner' },
    @{ Text = $ThemeInjectorRsText; Marker = 'cas-transfer-runtime-debug-banner' },
    @{ Text = $ThemeInjectorRsText; Marker = 'window.__casR94TurnCapability' },
    @{ Text = $ThemeInjectorRsText; Marker = '__casR94TimestampDiagnostics' },
    @{ Text = $ThemeInjectorRsText; Marker = '__casR94ComposerStatusDiagnostics' },
    @{ Text = $ThemeInjectorRsText; Marker = 'mount=' },
    @{ Text = $ThemeInjectorRsText; Marker = 'unsafe=' },
    @{ Text = $ThemeInjectorRsText; Marker = 'editorLeak=' },
    @{ Text = $ThemeInjectorRsText; Marker = 'Status src=' },
    @{ Text = $ThemeInjectorRsText; Marker = 'Pane owners=' },
    @{ Text = $ThemeInjectorRsText; Marker = 'exactUsageThreads=' },
    @{ Text = $ThemeInjectorRsText; Marker = 'SEGMode=' },
    @{ Text = $ThemeInjectorRsText; Marker = 'Timeline=' },
    @{ Text = $ThemeInjectorRsText; Marker = 'TS obs/vis/badge/cache' },
    @{ Text = $ThemeInjectorRsText; Marker = 'Collector tick=' },
    @{ Text = $ThemeInjectorRsText; Marker = '__casR94LocalUsageCollectorDiagnostics' },
    @{ Text = $ThemeInjectorRsText; Marker = 'SEG stamp/badge/cache' },
    @{ Text = $ThemeInjectorRsText; Marker = 'TL meta=' },
    @{ Text = $ThemeInjectorRsText; Marker = "data-cas-status-inside-composer" },
    @{ Text = $ThemeInjectorRsText; Marker = 'CAS-R94-1-RUNTIME-DEBUG-DRAG' },
    @{ Text = $ThemeInjectorRsText; Marker = 'CAS-R94-1-RUNTIME-DEBUG-COLLAPSE' },
    @{ Text = $ThemeInjectorRsText; Marker = 'data-cas-runtime-debug-draggable' },
    @{ Text = $ThemeInjectorRsText; Marker = 'data-cas-runtime-debug-collapsed' },
    @{ Text = $ThemeInjectorRsText; Marker = 'DRAG_THRESHOLD_PX' },
    @{ Text = $ThemeInjectorRsText; Marker = 'dragState.dragging === false' },
    @{ Text = $ThemeInjectorRsText; Marker = 'Click anywhere to collapse/expand' },
    @{ Text = $ThemeInjectorRsText; Marker = 'clampRootPosition' },
    @{ Text = $ThemeInjectorRsText; Marker = 'setPointerCapture' }
)
foreach ($Contract in $RuntimeDebugContracts) {
    if (-not $Contract.Text.Contains($Contract.Marker)) {
        throw "r94 runtime debug identity contract missing: $($Contract.Marker)"
    }
}
Write-Host 'R94_RUNTIME_DEBUG_IDENTITY_PREFLIGHT_PASS' -ForegroundColor Green
if (-not $CargoTomlText.Contains('version = "2.4.5+94.1"')) {
    throw 'r94.1 backend Cargo package version is not 2.4.5+94.1'
}
if (-not $CargoLockText.Contains('name = "codex-app-transfer"') -or
    -not $CargoLockText.Contains('version = "2.4.5+94.1"')) {
    throw 'r94.1 Cargo.lock app package identity is not 2.4.5+94.1'
}
Write-Host 'R94_BACKEND_PACKAGE_IDENTITY_PREFLIGHT_PASS' -ForegroundColor Green

if ($R941ApplyRsText -match '(?m)^\s*(?:&&|\|\|)\s+let\s+') {
    throw 'r94.1 Rust 2024 let-chain syntax detected in Rust 2021 workspace'
}
Write-Host 'R94_1_RUST_2021_SYNTAX_COMPAT_PASS' -ForegroundColor Green

foreach ($Marker in @(
    'CAS-R94-1-PROVIDER-CONFIG-TRUTH',
    'CAS-R94-1-TRANSFER-ONLY-PROVIDER-POLICY-OBSERVATION',
    'CAS-R94-1-EXTERNAL-CATALOG-AUTHORITY',
    'provider_section_fields',
    'section_requires_quoted_key',
    'behavior_fields',
    'sync_root_value(&paths.config_toml, "model_provider", None)',
    'transfer-only-observed-stock-openai-policy-not-overridable',
    'CAS-R94-1-LIVE-PROVIDER-IDENTITY-CHANGED',
    'CAS-R94-1-BUILTIN-OPENAI-IDENTITY-RESTORE',
    'r94_1_provider_policy_truth_reads_custom_provider_fields',
    'r94_1_provider_policy_reader_accepts_plain_header_comment',
    'r94_1_provider_policy_parser_marks_quoted_and_nested_forms',
    'r94_1_live_provider_switch_in_same_session_fails_before_mutation',
    'r94_1_expected_root_provider_absence_reuses_snapshot_source_without_fake_overlay',
    'r94_1_identity_only_provider_can_repeat_after_transfer_strips_root_identity',
    'r94_1_provider_policy_is_observed_but_not_copied_to_builtin_openai',
    'r94_1_builtin_openai_table_is_left_user_owned',
    'snapshot_toml_value_literal(snapshot_config, "model_context_window")',
    'model_context_window_set: !preserve_external_model_catalog',
    'r94_1_external_catalog_removes_transfer_only_global_window',
    'r94_1_external_catalog_preserves_ambiguous_post_snapshot_live_window',
    'r94_1_external_catalog_preserves_user_owned_global_window',
    'action = "remove-proven-transfer-root-window"',
    'action = "preserve-ambiguous-live-root-window"'
)) {
    if (-not $R941ApplyRsText.Contains($Marker)) {
        throw "r94.1 Transfer-only provider/config truth contract missing: $Marker"
    }
}

foreach ($Forbidden in @(
    'CAS-R94-1-BUILTIN-OPENAI-POLICY-OVERLAY',
    'OPENAI_POLICY_OVERLAY_FIELDS',
    'write_openai_policy_overlay',
    'restore_openai_policy_overlay',
    'CAS-R94-1-BUILTIN-OPENAI-RUNTIME-REQUIRED',
    'codex-r94.1-runtime',
    'CAS_R94_1_CODEX_RUNTIME_EXE',
    'CAS_R94_1_OPENAI_POLICY_OVERLAY',
    'custom-provider-policy-preserved',
    'CAS-R94-1-CUSTOM-PROVIDER-ROUTE-CANARY',
    'provider_policy_carry_forward_block_reason',
    'Some(&provider_literal)',
    'sync_root_value(&paths.config_toml, "stream_max_retries"',
    'sync_root_value(&paths.config_toml, "request_max_retries"',
    'sync_root_value(&paths.config_toml, "stream_idle_timeout_ms"',
    'sync_root_value(&paths.config_toml, "websocket_connect_timeout_ms"',
    'sync_table_field(&paths.config_toml, "model_providers.openai"'
)) {
    if ($R941ApplyRsText.Contains($Forbidden)) {
        throw "r94.1 Transfer-only provider/config contract violated: $Forbidden"
    }
}

$DoubleSuffix = '94.1' + '.1'
if ($MyInvocation.MyCommand.Path -and ([System.IO.File]::ReadAllText($MyInvocation.MyCommand.Path)).Contains($DoubleSuffix)) {
    throw ("r94.1 build source contains a double-suffixed preview identity: " + $DoubleSuffix)
}
Write-Host 'R94_1_PREVIEW_IDENTITY_SANITY_PASS' -ForegroundColor Green

Write-Host 'R94_1_TRANSFER_ONLY_PROVIDER_CONFIG_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host '  - Transfer keeps the effective Codex provider on built-in openai'
Write-Host '  - user custom-provider tables and behavior fields remain user-owned and untouched'
Write-Host '  - provider behavior is parsed for diagnostics only; r94.1 does not write a cosmetic [model_providers.openai] override'
Write-Host '  - no Codex binary, app-server, MSIX content or private runtime is patched/replaced'
Write-Host '  - same-session model_provider identity changes still fail closed before Transfer overwrites the user edit'
Write-Host '  - external catalog ownership rules remain unchanged'

foreach ($Marker in @(
    'CAS-R94-TURN-AWARE-ROLLOUT-BRIDGE',
    'CAS-R94-ACTIVE-THREAD-FALLBACK',
    'CAS-R94-MULTI-PANE-THREAD-COLLECTOR',
    'const out=[];const seen=new Set();',
    'if(out.length)return out;',
    'data-above-composer-conversation-id',
    'Array.isArray(threadValue)',
    'for (const threadId of threadIds)',
    'item_started|item_completed',
    'recentItems: Array.from(itemMeta.values()).slice(-96)',
    'safeEnvelope.recentItems = Array.isArray(envelope.recentItems)',
    'R94_USAGE_LOOKUP_MISS_TTL_MS = 10000',
    'CAS-R94-LOCAL-USAGE-COLLECTOR-DIAGNOSTICS',
    'CAS-R94-EXACT-INGEST-ACK-DIAGNOSTICS',
    '__casR94LocalUsageCollectorDiagnostics',
    "stage: 'file-miss'",
    "stage: 'envelope-miss'",
    "'ingest-missing'",
    "'ingest-ok'",
    "pushOk: !!(pushed && pushed.ok)",
    'data-cas-pane-statusbar=\"true\"][data-cas-pane-thread-id]',
    'localUsageMissCache.set(normalized, Date.now());',
    'localUsageSnapshotCache.set(filePath, { size: stat.size, envelope: fallbackEnvelope });',
    'terminalTurn',
    'activeTurn',
    'turnCompletedAt',
    'turnDurationMs',
    'safeEnvelope.turnId = envelope.turnId || null;',
    'safeEnvelope.terminalTurn = envelope.terminalTurn || null;',
    "model: latestUsage.model || (usageTurn && usageTurn.model) || null,",
    "const model = typeof payload?.model === 'string' ? payload.model.trim() : '';",
    'Keep the historical r83 exact-replacement anchor intact'
)) {
    if (-not $R76OutputOwnerText.Contains($Marker)) {
        throw "r94 r76 rollout bridge contract missing: $Marker"
    }
}
$R83SafeEnvelopeAnchor = @'
    const safeEnvelope = {
      threadId: normalizeUsageThreadId(threadId),
      updatedAt: envelope.updatedAt,
      info: envelope.info,
    };
'@
if (-not $R76OutputOwnerText.Contains((Normalize-Eol $R83SafeEnvelopeAnchor))) {
    throw 'r94 r76 collector no longer preserves the r83 safe-envelope exact replacement anchor'
}
Write-Host 'R94_R83_COLLECTOR_COMPAT_PREFLIGHT_PASS' -ForegroundColor Green
foreach ($Forbidden in @(
    'readFile(filePath',
    'readFileSync(filePath'
)) {
    if ($R76OutputOwnerText.Contains($Forbidden)) {
        throw "r94 rollout bridge regressed to whole-file parsing: $Forbidden"
    }
}
Write-Host 'R94_R76_TURN_AWARE_ROLLOUT_BRIDGE_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host 'R94_R76_ACTIVE_THREAD_FALLBACK_AND_MISS_CACHE_PASS' -ForegroundColor Green
Write-Host 'R94_MULTI_PANE_SUBAGENT_TELEMETRY_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host 'R94_R77_ACTIVE_THREAD_RESOLVER_COMPAT_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host 'R94_TIMESTAMP_VISIBLE_NATIVE_GATE_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host 'R94_NATIVE_SINGLE_PANE_USAGE_FALLBACK_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host 'R94_EXACT_USAGE_INGEST_EXPORT_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host 'R94_STATUS_TRUTH_SEMANTICS_PREFLIGHT_PASS' -ForegroundColor Green
Write-Host '  - ctx uses Codex last_token_usage.total_tokens / model_context_window on exact JSONL'
Write-Host '  - in/out mean latest model request, session means cumulative total_token_usage'
Write-Host '  - parent/sub-agent panes retain their last exact same-thread snapshot while a newer turn waits for its first token update'
Write-Host '  - pane tok/s is derived only from consecutive exact same-thread+same-turn output-token samples'
Write-Host '  - native/global tok/s is never relabeled as pane-local speed; first exact sample remains -- until a delta exists'
Write-Host '  - unavailable sid is omitted instead of rendering a permanent sid -- placeholder'
Write-Host 'R94_LOCAL_USAGE_COLLECTOR_DIAGNOSTICS_PREFLIGHT_PASS' -ForegroundColor Green


try {
    Write-Utf8NoBom $TempOverlayCheck ("function __r94OverlaySyntaxOnly(){`n" + $OverlayJs + "`n}`n")
    & node --check $TempOverlayCheck
    if ($LASTEXITCODE -ne 0) { throw 'r94 exact turn overlay JavaScript syntax check failed' }

    Write-Utf8NoBom $TempStampCheck ("function __r94StampSyntaxOnly(){`n" + $DisabledStampJs + "`n}`n")
    & node --check $TempStampCheck
    if ($LASTEXITCODE -ne 0) { throw 'r94 disabled stamp JavaScript syntax check failed' }
    Write-Host 'R94_EXACT_TURN_JS_SYNTAX_PASS' -ForegroundColor Green

    # Start from the frozen r90 generator so pane ownership/WAITING/truth-first
    # telemetry stay inherited. r94 replaces the final timestamp owner and adds exact turn/status capability.
    $Builder = $Builder.Replace('R90','R94').Replace('r90','r94').Replace('+90','+94')
    # r94.1 preview identity: internal R94 filenames/markers stay unchanged so
    # the already-validated exact-turn/timestamp pipeline is not renamed.
    $Builder = $Builder.Replace('2.4.5+94','2.4.5+94.1')
    $Builder = $Builder.Replace('Sub2API Grok Compat r94','Sub2API Grok Compat r94.1')
    $Builder = $Builder.Replace('visible/package identity is r94 / 2.4.5+94.1','visible/package identity is r94.1 / 2.4.5+94.1')

    # r94.1 identity must propagate one level deeper too. The retargeted r90
    # builder creates its own r94 wrapper from the frozen r89 baseline; without
    # this patch that nested wrapper still emits r94 / 2.4.5+94 while its
    # invariant has already been retargeted to r94.1.
    $OldNestedIdentityRetarget = @'
$R94Builder = $OriginalBuilder.Replace('R89','R94').Replace('r89','r94').Replace('+89','+94')
'@
    $NewNestedIdentityRetarget = @'
$R94Builder = $OriginalBuilder.Replace('R89','R94').Replace('r89','r94').Replace('+89','+94')
$R94Builder = $R94Builder.Replace('2.4.5+94','2.4.5+94.1')
$R94Builder = $R94Builder.Replace('Sub2API Grok Compat r94','Sub2API Grok Compat r94.1')
$R94Builder = $R94Builder.Replace('visible/package identity is r94 / 2.4.5+94.1','visible/package identity is r94.1 / 2.4.5+94.1')

# r89 itself materializes an r88-derived wrapper. Promote that generated text
# before its r94.1 invariant runs, otherwise the child still reports +94.
$R941R88Retarget = "    `$R94 = `$OriginalR88.Replace('r88','r94').Replace('R88','R94').Replace('+88','+94')"
if (-not $R94Builder.Contains($R941R88Retarget)) {
    throw 'r94.1 could not locate nested r88 identity retarget'
}
$R941R88Replacement = $R941R88Retarget +
    "`n    `$R94 = `$R94.Replace('2.4.5+94','2.4.5+94.1')" +
    "`n    `$R94 = `$R94.Replace('Sub2API Grok Compat r94','Sub2API Grok Compat r94.1')" +
    "`n    `$R94 = `$R94.Replace('visible/package identity is r94 / 2.4.5+94.1','visible/package identity is r94.1 / 2.4.5+94.1')"
$R94Builder = $R94Builder.Replace($R941R88Retarget,$R941R88Replacement)
'@
    $Builder = Replace-Required $Builder $OldNestedIdentityRetarget $NewNestedIdentityRetarget 'r94.1 nested generated builder identity propagation'

    $OldPaneSource = "`$R89PanePatch = Join-Path `$PSScriptRoot 'r89-r75-pane-runtime-patch-v4.inc.ps1'"
    $NewPaneSource = "`$R89PanePatch = Join-Path `$PSScriptRoot '.r94-r89-pane-runtime-patch.generated.inc.ps1'"
    $Builder = Replace-Required $Builder $OldPaneSource $NewPaneSource 'temporary exact-overlay pane include path'

    # The frozen r90 source predates our strict EOL discipline. Normalize its
    # generated replacement helpers so the exact owner patch is Windows-safe.
    $OldReplaceRequired = @'
function Replace-Required([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    if (-not $Text.Contains($Old)) { throw "r94 expected text missing: $Label" }
    return $Text.Replace($Old,$New)
}
'@
    $NewReplaceRequired = @'
function Replace-Required([string]$Text,[string]$Old,[string]$New,[string]$Label) {
    $NormalizedText = $Text.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedOld = $Old.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedNew = $New.Replace("`r`n","`n").Replace("`r","`n")
    if (-not $NormalizedText.Contains($NormalizedOld)) { throw "r94 expected text missing: $Label" }
    return $NormalizedText.Replace($NormalizedOld,$NormalizedNew)
}
'@
    $Builder = Replace-Required $Builder $OldReplaceRequired $NewReplaceRequired 'EOL-safe generated Replace-Required'

    $OldReplaceBlock = @'
function Replace-BlockRequired([string]$Text,[string]$Start,[string]$End,[string]$Replacement,[string]$Label) {
    $StartIndex = $Text.IndexOf($Start)
    if ($StartIndex -lt 0) { throw "r94 block start missing: $Label" }
    $EndIndex = $Text.IndexOf($End,$StartIndex + $Start.Length)
    if ($EndIndex -le $StartIndex) { throw "r94 block end missing: $Label" }
    return $Text.Substring(0,$StartIndex) + $Replacement + "`n`n" + $Text.Substring($EndIndex)
}
'@
    $NewReplaceBlock = @'
function Replace-BlockRequired([string]$Text,[string]$Start,[string]$End,[string]$Replacement,[string]$Label) {
    $NormalizedText = $Text.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedStart = $Start.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedEnd = $End.Replace("`r`n","`n").Replace("`r","`n")
    $NormalizedReplacement = $Replacement.Replace("`r`n","`n").Replace("`r","`n")
    $StartIndex = $NormalizedText.IndexOf($NormalizedStart)
    if ($StartIndex -lt 0) { throw "r94 block start missing: $Label" }
    $EndIndex = $NormalizedText.IndexOf($NormalizedEnd,$StartIndex + $NormalizedStart.Length)
    if ($EndIndex -le $StartIndex) { throw "r94 block end missing: $Label" }
    return $NormalizedText.Substring(0,$StartIndex) + $NormalizedReplacement + "`n`n" + $NormalizedText.Substring($EndIndex)
}
'@
    $Builder = Replace-Required $Builder $OldReplaceBlock $NewReplaceBlock 'EOL-safe generated Replace-BlockRequired'

    # Keep the stable pane/status owner patch, then replace only the timestamp
    # generation owner at that same nested layer.
    $PanePatch = $PanePatch + "`n`n" + $ExactOverlayPatch

    # These invariants inspect the generated r90->r94 builder source *before*
    # that builder executes. For the r88 child promotion, therefore validate the
    # string-construction owner ($R941R88Replacement), not the future expanded
    # child line "$R94 = $R94.Replace(...)" which does not exist until runtime.
    foreach ($Marker in @(
        "`$TempObserver = Join-Path `$PSScriptRoot 'r94-timestamp-observer.js'",
        "`$TempPaneJs = Join-Path `$PSScriptRoot 'r94-pane-runtime.js'",
        "`$TempTruthJs = Join-Path `$PSScriptRoot 'r94-telemetry-truth.js'",
        'R94_SEMANTIC_RUNTIME_CORRECTNESS_PASS',
        'visible/package identity is r94.1 / 2.4.5+94.1',
        "`$R94Builder = `$R94Builder.Replace('2.4.5+94','2.4.5+94.1')",
        'r94.1 could not locate nested r88 identity retarget',
        '$R941R88Replacement = $R941R88Retarget +',
        "Replace('visible/package identity is r94 / 2.4.5+94.1','visible/package identity is r94.1 / 2.4.5+94.1')",
        '.r94-r89-pane-runtime-patch.generated.inc.ps1'
    )) {
        if (-not $Builder.Contains($Marker)) { throw "r94 retargeted builder invariant missing: $Marker" }
    }

    foreach ($Marker in @(
        'R89_PANE_RUNTIME_GENERATION_PATCH_V4',
        'R94_EXACT_TIMESTAMP_OVERLAY_GENERATION_PATCH',
        'R94_FINAL_TIMESTAMP_OWNERS_REPLACED_PASS'
    )) {
        if (-not $PanePatch.Contains($Marker)) { throw "r94 generated pane include missing marker: $Marker" }
    }

    Assert-PowerShellParses $ExactOverlayPatch 'r94 exact turn owner patch'
    Assert-PowerShellParses $PanePatch 'r94 generated pane include'
    Assert-PowerShellParses $Builder 'r94 retargeted r90 builder'
    Write-Host 'R94_GENERATED_POWERSHELL_PARSE_PASS' -ForegroundColor Green

    Write-Utf8NoBom $TempPanePatch $PanePatch
    Write-Utf8NoBom $TempBuilder $Builder

    $Args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$TempBuilder)
    if ($RunFocusedTests) { $Args += '-RunFocusedTests' }
    if ($PreflightOnly) { $Args += '-PreflightOnly' }

    & pwsh @Args
    if ($LASTEXITCODE -ne 0) { throw "r94 delegated build failed with exit code $LASTEXITCODE" }

    $DirtyAfter = @(git -C $RepoRoot status --porcelain --untracked-files=no)
    if ($LASTEXITCODE -ne 0) { throw 'r94 post-build git status failed' }
    if ($DirtyAfter.Count -gt 0) { throw "r94 delegated build left tracked changes:`n$($DirtyAfter -join "`n")" }

    if ($PreflightOnly) {
        Write-Host 'R94_EXACT_TURN_PREFLIGHT_ONLY_PASS' -ForegroundColor Green
        Write-Host '  - r90 pane ownership / WAITING / truth-first telemetry remains inherited'
        Write-Host '  - legacy per-segment timestamp stamping is disabled at the final r86/r78 owner'
        Write-Host '  - native final/user timestamps remain authoritative; live assistant/progress/tool blocks get host first-observed ≈ YYYY-MM-DD HH:mm:ss timestamps'
        Write-Host '  - Codex official conversation rail/minimap is preserved unchanged; Transfer does not paint a second left rail'
        Write-Host '  - native Codex turn/action-row DOM is read-only; labels live in a Transfer-owned overlay root'
        Write-Host '  - mutation observation is childList-only; visible-turn work is IntersectionObserver bounded'
        Write-Host '  - historical/remounted blocks never receive host-now estimates; live segment discovery stays childList-only with no periodic timestamp sweep'
        Write-Host '  - status bar mounts only in a structurally verified composer shell, as a sibling of the editor branch; unsafe/unknown surfaces fail closed'
        Write-Host '  - native/global Usage polling cannot overwrite pane/local status counters or tok/s'
        Write-Host '  - exact TurnCapability accepts turn lifecycle + turn-scoped usage notifications when passively observed'
        Write-Host '  - r76 bounded rollout tail preserves task_started/turn_context/token_count/task_complete turn identity without whole-file parsing'
        Write-Host '  - repeated token_count/lifecycle payloads are fingerprint-deduped before UI refresh'
        Write-Host '  - composer status prefers exact threadId+turnId usage and only falls back to thread snapshot when no newer turn identity exists'
        Write-Host '  - native final timestamp ownership is never duplicated, even when Codex reveals that timestamp only on hover'
        Write-Host '  - Runtime Debug is off by default; when enabled it shows DBG94.1-1 identity in Transfer and injects live MATCH/LEGACY/MISSING evidence into Codex'
    } else {
        Write-Host ''
        Write-Host 'R94_EXACT_TURN_RUNTIME_PASS' -ForegroundColor Green
        Write-Host '  - hybrid timestamp overlay keeps native final/user times and adds ≈ YYYY-MM-DD HH:mm:ss first-observed time to each live output block'
        Write-Host '  - timeline metadata stays internal for diagnostics; visible navigation remains Codex-native to avoid duplicate UI and hot scroll work'
        Write-Host '  - legacy r74-r90 stamp path is inert'
        Write-Host '  - composer status is mounted in the rounded composer shell but outside the editable tree; telemetry can never become prompt text'
        Write-Host '  - exact turn capability is keyed by threadId + turnId and native duplicate timestamps are suppressed'
        Write-Host '  - local rollout task/token events are normalized into the same bounded capability without provider/app-server probes'
        Write-Host '  - pane status consumes exact recent-turn usage when available; native/global Usage is never borrowed'
        Write-Host '  - optional Runtime Debug (DBG94.1-1) exposes package/runtime/PID evidence in Transfer and the live Codex renderer'
        Write-Host 'R94_1_TRANSFER_ONLY_PROVIDER_CONFIG_RUNTIME_PASS' -ForegroundColor Green
        Write-Host '  - effective provider remains built-in openai'
        Write-Host '  - user provider tables remain untouched; behavior fields are observed but not falsely claimed effective on stock Codex'
        Write-Host '  - Transfer does not patch or replace Codex runtime/app-server'
        Write-Host '  - external model catalog owns per-model context; user-owned/ambiguous live root overrides are never silently deleted'
        Write-Host '  - runtime debug panel is freely draggable for this session'
        Write-Host '  - visible/package identity is r94.1 / 2.4.5+94.1'
    }
}
finally {
    foreach ($Path in @($TempBuilder,$TempPanePatch,$TempOverlayCheck,$TempStampCheck)) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    }
    Write-Host '[r94] removed generated helpers; r93/r92/r90/r89 tracked baselines remain untouched'
}
