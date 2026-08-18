from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src-tauri/src/codex_quota_injector.rs"
MARKER = "CAS-R38-CODEX-USAGE-INJECTOR-COMPAT"

body = PATH.read_text(encoding="utf-8")
if MARKER in body:
    print("r38 quota injector core: already applied")
    raise SystemExit(0)

old = "use serde_json::json;\n\nuse futures::{SinkExt, StreamExt};"
new = (
    "use serde::{Deserialize, Serialize};\n"
    "use serde_json::json;\n"
    "use std::sync::{Mutex, OnceLock};\n\n"
    "use futures::{SinkExt, StreamExt};"
)
if old not in body:
    raise SystemExit("r38 quota injector core: serde import anchor missing")
body = body.replace(old, new, 1)

old = "  var VERSION = 7; // bump:缓存命中趋势浮层去掉左侧竖排标题(仅留 y 刻度 + 折线)→ 升级后免重启 Codex 即覆盖旧注入"
new = "  var VERSION = 8; // CAS-R38-CODEX-USAGE-INJECTOR-COMPAT: multi-anchor + diagnostics + context-independent mount"
if old not in body:
    raise SystemExit("r38 quota injector core: VERSION=7 anchor missing")
body = body.replace(old, new, 1)

old = "  window.__catQuotaVersion = VERSION;\n  window.__catQuotaLast = null;\n  window.__catQuotaSig = null;\n"
new = r'''  window.__catQuotaVersion = VERSION;
  window.__catQuotaLast = null;
  window.__catQuotaSig = null;
  window.__catQuotaDiag = {
    scriptInstalled: false,
    panelPresent: false,
    anchorKind: 'none',
    contextSource: 'unavailable',
    conversationIdFound: false
  };
  function setQuotaDiag(key, value) {
    if (window.__catQuotaDiag) window.__catQuotaDiag[key] = value;
  }
  window.__catQuotaDiagnostic = function() {
    var d = window.__catQuotaDiag || {};
    return {
      scriptInstalled: !!d.scriptInstalled,
      panelPresent: !!d.panelPresent,
      anchorKind: d.anchorKind || 'none',
      contextSource: d.contextSource || 'unavailable',
      conversationIdFound: !!d.conversationIdFound
    };
  };
'''
if old not in body:
    raise SystemExit("r38 quota injector core: diagnostic insertion anchor missing")
body = body.replace(old, new, 1)

start = body.find("  function findScroller() {")
end = body.find("\n\n  function el(", start)
if start < 0 or end < 0:
    raise SystemExit("r38 quota injector core: findScroller block missing")
find_scroller = r'''  function isVisibleElement(el) {
    if (!el || el === document.body || el === document.documentElement) return false;
    try {
      var rc = el.getBoundingClientRect();
      var cs = window.getComputedStyle(el);
      return rc.width > 0 && rc.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden';
    } catch (e) { return false; }
  }

  function knownSummaryLabelHits(root) {
    if (!root) return 0;
    var text = (root.innerText || root.textContent || '').toLowerCase();
    var groups = [
      ['environment', '环境'],
      ['sources', 'source', '来源']
    ];
    var hits = 0;
    groups.forEach(function(g) {
      if (g.some(function(k) { return text.indexOf(k) >= 0; })) hits++;
    });
    return hits;
  }

  function popupAncestor(el) {
    if (!el || !el.closest) return null;
    return el.closest('[role="dialog"],[role="menu"],[data-radix-popper-content-wrapper],[data-side],[data-align]');
  }

  function sectionParentCandidate(parent) {
    if (!parent || !isVisibleElement(parent)) return false;
    var directSections = Array.prototype.filter.call(parent.children || [], function(ch) {
      return ch && ch.tagName === 'SECTION';
    });
    if (directSections.length < 2) return false;
    var popup = popupAncestor(parent);
    if (popup && isVisibleElement(popup)) return true;
    return knownSummaryLabelHits(parent) >= 2;
  }

  function findScroller() {
    // Tier 1: historical 26.608 selector.
    var legacy = document.querySelectorAll('section header button[class~="group/section-toggle"]');
    for (var i = 0; i < legacy.length; i++) {
      var sec = legacy[i].closest('section');
      if (sec && sec.parentElement) return { node: sec.parentElement, kind: 'legacy-class' };
    }

    // Tier 2: semantic section headers. The parent must be inside a visible popup/dialog,
    // or contain both known pinned-summary labels; this avoids injecting into arbitrary pages.
    var buttons = document.querySelectorAll(
      'section header button[aria-expanded],section header button[aria-controls],section header button'
    );
    var seen = [];
    for (var j = 0; j < buttons.length; j++) {
      var s = buttons[j].closest && buttons[j].closest('section');
      var p = s && s.parentElement;
      if (!p || seen.indexOf(p) >= 0) continue;
      seen.push(p);
      if (sectionParentCandidate(p)) return { node: p, kind: 'semantic-section' };
    }

    // Tier 3: current popup may have lost the old Tailwind class / section-button shape.
    // Only accept a visible popup whose content identifies it as the pinned summary.
    var popups = document.querySelectorAll(
      '[role="dialog"],[role="menu"],[data-radix-popper-content-wrapper],[data-side],[data-align]'
    );
    for (var k = 0; k < popups.length; k++) {
      var pop = popups[k];
      if (!isVisibleElement(pop) || knownSummaryLabelHits(pop) < 2) continue;
      var sections = pop.querySelectorAll('section');
      for (var n = 0; n < sections.length; n++) {
        var parent = sections[n].parentElement;
        if (parent && sectionParentCandidate(parent)) {
          return { node: parent, kind: 'semantic-popup-sections' };
        }
      }
      var rc = pop.getBoundingClientRect();
      if (rc.width > 0 && rc.width < 1000 && rc.height > 0 && rc.height < 1100) {
        return { node: pop, kind: 'semantic-popup' };
      }
    }
    return null;
  }'''
body = body[:start] + find_scroller + body[end:]

# findScroller now returns {node,kind}; conversation-id probing needs the node itself.
old = "        findScroller(),\n        ctxSection ? ctxSection.previousElementSibling : null,"
new = "        (findScroller() || {}).node || null,\n        ctxSection ? ctxSection.previousElementSibling : null,"
if old not in body:
    raise SystemExit("r38 quota injector core: readConvId findScroller anchor missing")
body = body.replace(old, new, 1)

old = "  function refreshContext(node, cid) {\n    var w = node && node.querySelector('[data-ctx]');\n    if (!w) return;\n"
new = "  function refreshContext(node, cid) {\n    var w = node && node.querySelector('[data-ctx]');\n    if (!w) { setQuotaDiag('contextSource', 'unavailable'); return; }\n"
if old not in body:
    raise SystemExit("r38 quota injector core: refreshContext start anchor missing")
body = body.replace(old, new, 1)

old = "    var u = readCtxUsage();\n    if (u && u.effWin > 0) {\n"
new = "    var u = readCtxUsage();\n    if (u && u.effWin > 0) {\n      setQuotaDiag('contextSource', 'fiber');\n"
if old not in body:
    raise SystemExit("r38 quota injector core: fiber source anchor missing")
body = body.replace(old, new, 1)

old = "      var aria = readCtxPct();\n      var c = usageCacheGet(cid);\n"
new = "      var aria = readCtxPct();\n      setQuotaDiag('contextSource', aria != null ? 'aria' : 'unavailable');\n      var c = usageCacheGet(cid);\n"
if old not in body:
    raise SystemExit("r38 quota injector core: aria source anchor missing")
body = body.replace(old, new, 1)

old = '''  function ensureNode() {
    var data = window.__catQuotaLast;
    var node = document.getElementById('cat-quota-entry');
    if (!data || !data.rows || !data.rows.length) { if (node) node.remove(); return; }
    var scroller = findScroller();
    if (!scroller) { if (node) node.remove(); return; }
    ensureStyle();
'''
new = '''  function ensureNode() {
    var data = window.__catQuotaLast;
    var node = document.getElementById('cat-quota-entry');
    if (!data || !data.rows || !data.rows.length) {
      if (node) node.remove();
      setQuotaDiag('panelPresent', false);
      return;
    }
    var anchor = findScroller();
    var scroller = anchor && anchor.node;
    if (!scroller) {
      if (node) node.remove();
      setQuotaDiag('panelPresent', false);
      setQuotaDiag('anchorKind', 'none');
      return;
    }
    setQuotaDiag('anchorKind', anchor.kind || 'unknown');
    ensureStyle();
'''
if old not in body:
    raise SystemExit("r38 quota injector core: ensureNode anchor missing")
body = body.replace(old, new, 1)

old = '''    var cid = readConvId();
    refreshContext(node, cid);
    refreshTps(node, cid);
    refreshDuo(node, cid);
  }
'''
new = '''    setQuotaDiag('panelPresent', !!(node && node.isConnected));
    var cid = readConvId();
    setQuotaDiag('conversationIdFound', !!cid);
    refreshContext(node, cid);
    refreshTps(node, cid);
    refreshDuo(node, cid);
  }
'''
if old not in body:
    raise SystemExit("r38 quota injector core: ensureNode tail anchor missing")
body = body.replace(old, new, 1)

old = '''  // 置位放最后:若上方任一步抛异常(如极早期 document.body 为 null),
  // guard 不毒化,下一 tick 重装(review MEDIUM-2)
  window.__catQuotaInstalled = true;
'''
new = '''  // 置位放最后:若上方任一步抛异常(如极早期 document.body 为 null),
  // guard 不毒化,下一 tick 重装(review MEDIUM-2)
  window.__catQuotaInstalled = true;
  setQuotaDiag('scriptInstalled', true);
'''
if old not in body:
    raise SystemExit("r38 quota injector core: installed tail anchor missing")
body = body.replace(old, new, 1)

old = '''  delete window.__catQuotaSig;
  delete window.__catQuotaVersion;
  delete window.__catQuotaInstalled;
'''
new = '''  delete window.__catQuotaSig;
  delete window.__catQuotaVersion;
  delete window.__catQuotaDiag;
  delete window.__catQuotaDiagnostic;
  delete window.__catQuotaInstalled;
'''
if old not in body:
    raise SystemExit("r38 quota injector core: remove diagnostic anchor missing")
body = body.replace(old, new, 1)

anchor = "/// evaluate 失败的阶段 —— 决定日志级别(review HIGH-1):"
if anchor not in body:
    raise SystemExit("r38 quota injector core: PushError anchor missing")
status_code = r'''// CAS-R38-CODEX-USAGE-INJECTOR-COMPAT
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct QuotaInjectorStatus {
    pub enabled: bool,
    pub cdp_connected: bool,
    pub script_installed: bool,
    pub panel_present: bool,
    pub anchor_kind: String,
    pub context_source: String,
    pub conversation_id_found: bool,
    pub last_error: Option<String>,
}

impl Default for QuotaInjectorStatus {
    fn default() -> Self {
        Self {
            enabled: false,
            cdp_connected: false,
            script_installed: false,
            panel_present: false,
            anchor_kind: "none".to_owned(),
            context_source: "unavailable".to_owned(),
            conversation_id_found: false,
            last_error: None,
        }
    }
}

#[derive(Debug, Clone, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct QuotaJsDiag {
    script_installed: bool,
    panel_present: bool,
    anchor_kind: String,
    context_source: String,
    conversation_id_found: bool,
}

#[derive(Debug, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct QuotaPushResult {
    conv_id: Option<String>,
    diag: Option<QuotaJsDiag>,
}

static QUOTA_INJECTOR_STATUS: OnceLock<Mutex<QuotaInjectorStatus>> = OnceLock::new();

fn quota_status_cell() -> &'static Mutex<QuotaInjectorStatus> {
    QUOTA_INJECTOR_STATUS.get_or_init(|| Mutex::new(QuotaInjectorStatus::default()))
}

pub fn quota_injector_status() -> QuotaInjectorStatus {
    quota_status_cell()
        .lock()
        .map(|s| s.clone())
        .unwrap_or_default()
}

fn publish_quota_status(next: QuotaInjectorStatus) {
    let Ok(mut current) = quota_status_cell().lock() else { return; };
    if *current == next { return; }
    tracing::info!(
        target: "codex_quota_injector",
        enabled = next.enabled,
        cdp_connected = next.cdp_connected,
        script_installed = next.script_installed,
        panel_present = next.panel_present,
        anchor_kind = %next.anchor_kind,
        context_source = %next.context_source,
        conversation_id_found = next.conversation_id_found,
        last_error = ?next.last_error,
        "[Quota] injector state transition"
    );
    *current = next;
}

fn successful_quota_status(diag: Option<QuotaJsDiag>) -> QuotaInjectorStatus {
    let d = diag.unwrap_or_default();
    QuotaInjectorStatus {
        enabled: true,
        cdp_connected: true,
        script_installed: d.script_installed,
        panel_present: d.panel_present,
        anchor_kind: if d.anchor_kind.is_empty() { "none".to_owned() } else { d.anchor_kind },
        context_source: if d.context_source.is_empty() { "unavailable".to_owned() } else { d.context_source },
        conversation_id_found: d.conversation_id_found,
        last_error: None,
    }
}

'''
body = body.replace(anchor, status_code + anchor, 1)

start = body.find("async fn push_via_cdp(payload: Option<serde_json::Value>)")
end = body.find("\n}\n\n/// token 数紧凑格式", start)
if start < 0 or end < 0:
    raise SystemExit("r38 quota injector core: push_via_cdp function missing")
end += 2
push_fn = r'''async fn push_via_cdp(payload: Option<serde_json::Value>) -> Result<QuotaPushResult, PushError> {
    let update_arg = payload.unwrap_or(serde_json::Value::Null);
    let script = format!(
        "{INSTALL_SCRIPT}\nwindow.__catQuotaUpdate && window.__catQuotaUpdate({update_arg});\nJSON.stringify({{convId:(window.__catActiveConvId ? window.__catActiveConvId() : null),diag:(window.__catQuotaDiagnostic ? window.__catQuotaDiagnostic() : null)}});"
    );
    let raw = evaluate_once(&script).await?;
    match raw {
        Some(s) => serde_json::from_str::<QuotaPushResult>(&s)
            .map_err(|e| PushError::Evaluate(format!("quota diagnostic decode failed: {e}"))),
        None => Ok(QuotaPushResult::default()),
    }
}'''
body = body[:start] + push_fn + body[end:]

old = '''        if !enabled {
            // 额度面板关闭时仍跑 WorkBuddy 账号池守护:自动切换是后端能力,不依赖面板显示。
'''
new = '''        if !enabled {
            publish_quota_status(QuotaInjectorStatus::default());
            // 额度面板关闭时仍跑 WorkBuddy 账号池守护:自动切换是后端能力,不依赖面板显示。
'''
if old not in body:
    raise SystemExit("r38 quota injector core: disabled branch anchor missing")
body = body.replace(old, new, 1)

old = '''        match push_via_cdp(payload).await {
            // push 同时回读**当前**活动 conversationId,供下 tick 按 uuid 取累计。
            // Ok(None)=evaluate 成功但无可识别活动会话 → 下 tick fail-closed 显「—」。
            Ok(conv) => {
                evaluate_warned = false;
                last_conv_id = conv;
            }
            Err(e) => log_push_error(&e, "quota push", &mut evaluate_warned),
        }
'''
new = '''        match push_via_cdp(payload).await {
            Ok(result) => {
                evaluate_warned = false;
                publish_quota_status(successful_quota_status(result.diag));
                last_conv_id = result.conv_id;
            }
            Err(e) => {
                let mut status = quota_injector_status();
                status.enabled = true;
                match &e {
                    PushError::Connect(_) => {
                        status.cdp_connected = false;
                        status.script_installed = false;
                        status.panel_present = false;
                        status.anchor_kind = "none".to_owned();
                        status.context_source = "unavailable".to_owned();
                        status.conversation_id_found = false;
                        status.last_error = Some("codex_not_reachable".to_owned());
                    }
                    PushError::Evaluate(_) => {
                        status.cdp_connected = true;
                        status.last_error = Some("evaluate_failed".to_owned());
                    }
                }
                publish_quota_status(status);
                log_push_error(&e, "quota push", &mut evaluate_warned);
            }
        }
'''
if old not in body:
    raise SystemExit("r38 quota injector core: daemon push-match anchor missing")
body = body.replace(old, new, 1)

insert = r'''
    #[test]
    fn r38_usage_injector_compat_contract() {
        assert!(INSTALL_SCRIPT.contains("CAS-R38-CODEX-USAGE-INJECTOR-COMPAT"));
        assert!(INSTALL_SCRIPT.contains("var VERSION = 8"));
        assert!(INSTALL_SCRIPT.contains("semantic-section"));
        assert!(INSTALL_SCRIPT.contains("semantic-popup"));
        assert!(INSTALL_SCRIPT.contains("__catQuotaDiagnostic"));
        assert!(INSTALL_SCRIPT.contains("contextSource"));
        assert!(INSTALL_SCRIPT.contains("panelPresent"));
        assert!(REMOVE_SCRIPT.contains("__catQuotaDiagnostic"));
        let s = QuotaInjectorStatus::default();
        assert!(!s.enabled && !s.cdp_connected && !s.panel_present);
    }
'''
pos = body.rfind("\n}")
if pos < 0:
    raise SystemExit("r38 quota injector core: final test-module brace missing")
body = body[:pos] + insert + body[pos:]

for token in (
    MARKER,
    "var VERSION = 8",
    "semantic-section",
    "semantic-popup",
    "__catQuotaDiagnostic",
    "QuotaInjectorStatus",
    "codex_not_reachable",
):
    if token not in body:
        raise SystemExit(f"r38 quota injector core missing token: {token}")

PATH.write_text(body, encoding="utf-8")
print("r38 quota injector core: applied")
