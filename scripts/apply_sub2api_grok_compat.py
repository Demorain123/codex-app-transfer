from pathlib import Path
import re

RESPONSES = Path("crates/adapters/src/mapper/responses.rs")
MAPPER_MOD = Path("crates/adapters/src/mapper/mod.rs")
COMPAT = Path("crates/adapters/src/mapper/sub2api_grok_compat.rs")
COMPAT_TEMPLATE = Path("scripts/sub2api_grok_compat_overlay.rs")
HOOK = "// CAS-SUB2API-GROK-COMPAT-HOOK"
TOOL_DIAG_HOOK = "// CAS-SUB2API-GROK-TOOL-INVENTORY-DIAG-HOOK"


def remove_rust_module(text: str, marker: str) -> str:
    """Remove a Rust module beginning at marker by brace counting."""
    start = text.find(marker)
    if start < 0:
        return text
    brace = text.find("{", start)
    if brace < 0:
        raise SystemExit(f"malformed module at {marker}")

    depth = 0
    i = brace
    in_str = False
    escape = False
    while i < len(text):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    while end < len(text) and text[end] in " \t\r\n":
                        end += 1
                    return text[:start] + text[end:]
        i += 1
    raise SystemExit(f"unterminated module at {marker}")


def dedupe_regex(text: str, pattern: re.Pattern[str], label: str) -> str:
    """Keep the first semantic hook and remove later duplicates, rustfmt-safe."""
    matches = list(pattern.finditer(text))
    if len(matches) <= 1:
        return text
    for match in reversed(matches[1:]):
        text = text[: match.start()] + text[match.end() :]
    print(f"[ok] {label}: removed {len(matches) - 1} duplicate(s)")
    return text


# ---------------------------------------------------------------------------
# 1. Authoritative runtime lives in a standalone Rust overlay template.
# ---------------------------------------------------------------------------
if not COMPAT_TEMPLATE.is_file():
    raise SystemExit(f"missing overlay template: {COMPAT_TEMPLATE}")
COMPAT.parent.mkdir(parents=True, exist_ok=True)
COMPAT.write_text(COMPAT_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
print(f"[ok] overlay module refreshed: {COMPAT}")

# Diagnostic-only helper. Keep it installed by the overlay patcher rather than
# upstream core so future official rebases remain thin. It logs only tool names,
# types and counts — never prompts, arguments, schemas, API keys or file contents.
# The app's tracing bridge already forwards workspace `tracing::*` events into
# proxy_telemetry().logs, so these lines automatically appear in the existing
# modified-version log UI/file without a second logging subsystem.
diag_helper = r'''
// CAS-SUB2API-GROK-TOOL-INVENTORY-DIAG-HOOK
#[derive(Debug)]
struct GrokToolInventoryDiag {
    total: usize,
    types: String,
    apply_patch: String,
    tool_search: String,
    names: String,
}

fn grok_tool_name(tool: &Value) -> Option<&str> {
    tool.get("name")
        .and_then(Value::as_str)
        .or_else(|| {
            tool.get("function")
                .and_then(|v| v.get("name"))
                .and_then(Value::as_str)
        })
}

fn summarize_grok_tool_inventory(body: &Bytes) -> Result<(String, GrokToolInventoryDiag), String> {
    let parsed = serde_json::from_slice::<Value>(body)
        .map_err(|err| format!("invalid request JSON: {err}"))?;
    let model = parsed
        .get("model")
        .and_then(Value::as_str)
        .unwrap_or("<missing>")
        .to_owned();
    let tools = parsed
        .get("tools")
        .and_then(Value::as_array)
        .map(|v| v.as_slice())
        .unwrap_or(&[]);

    let mut type_counts = std::collections::BTreeMap::<String, usize>::new();
    let mut apply_patch_types = std::collections::BTreeSet::<String>::new();
    let mut tool_search_types = std::collections::BTreeSet::<String>::new();
    let mut names = std::collections::BTreeSet::<String>::new();

    for tool in tools {
        let kind = tool
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or("unknown")
            .to_owned();
        *type_counts.entry(kind.clone()).or_insert(0) += 1;

        let name = grok_tool_name(tool).unwrap_or("");
        let display_name = if name.is_empty() { "<unnamed>" } else { name };
        names.insert(format!("{kind}:{display_name}"));

        if name == "apply_patch" {
            apply_patch_types.insert(kind.clone());
        }
        if kind == "tool_search" || name == "tool_search" {
            tool_search_types.insert(kind);
        }
    }

    let types = if type_counts.is_empty() {
        "none".to_owned()
    } else {
        type_counts
            .iter()
            .map(|(kind, count)| format!("{kind}:{count}"))
            .collect::<Vec<_>>()
            .join(",")
    };
    let apply_patch = if apply_patch_types.is_empty() {
        "absent".to_owned()
    } else {
        apply_patch_types.into_iter().collect::<Vec<_>>().join("|")
    };
    let tool_search = if tool_search_types.is_empty() {
        "absent".to_owned()
    } else {
        tool_search_types.into_iter().collect::<Vec<_>>().join("|")
    };

    // Tool inventories can be large when MCP namespaces are present. Keep the
    // line useful but bounded so diagnostics never swamp the normal proxy log.
    let all_names = names.into_iter().collect::<Vec<_>>();
    let shown = all_names.len().min(24);
    let mut names = all_names[..shown].join(",");
    if all_names.len() > shown {
        names.push_str(&format!(",…(+{})", all_names.len() - shown));
    }
    if names.is_empty() {
        names = "none".to_owned();
    }

    Ok((
        model,
        GrokToolInventoryDiag {
            total: tools.len(),
            types,
            apply_patch,
            tool_search,
            names,
        },
    ))
}

/// Compact request-side diagnostic for the exact question "did Codex advertise
/// apply_patch, and did the Grok compatibility lowering preserve it?".
///
/// `stage=inbound` is the Codex request before Grok lowering.
/// `stage=outbound` is the final body after Grok lowering/cache companions, i.e.
/// what the proxy is about to send upstream.
pub(crate) fn log_sub2api_grok_tool_inventory(stage: &str, body: &Bytes, provider: &Provider) {
    let enabled = provider
        .extra
        .get("sub2apiGrokCompat")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if !enabled {
        return;
    }

    match summarize_grok_tool_inventory(body) {
        Ok((model, summary)) => {
            let lower = model.trim().to_ascii_lowercase();
            if !(lower == "grok" || lower.starts_with("grok-") || lower.starts_with("grok/")) {
                return;
            }
            tracing::info!(
                target: "adapters::grok_tool_diag",
                stage = %stage,
                provider = %provider.id,
                model = %model,
                tools = summary.total,
                types = %summary.types,
                apply_patch = %summary.apply_patch,
                tool_search = %summary.tool_search,
                names = %summary.names,
                "Sub2API Grok tool inventory"
            );
        }
        Err(reason) => {
            tracing::warn!(
                target: "adapters::grok_tool_diag",
                stage = %stage,
                provider = %provider.id,
                reason = %reason,
                "Sub2API Grok tool inventory unavailable"
            );
        }
    }
}
'''
compat_text = COMPAT.read_text(encoding="utf-8")
test_anchor = "\n#[cfg(test)]\nmod tests {"
if TOOL_DIAG_HOOK not in compat_text:
    if test_anchor not in compat_text:
        raise SystemExit("missing anchor: compat tests module for tool diagnostic helper")
    compat_text = compat_text.replace(test_anchor, "\n" + diag_helper + test_anchor, 1)
    COMPAT.write_text(compat_text, encoding="utf-8")
    print("[ok] Grok tool inventory diagnostic helper: applied")
else:
    print("[ok] Grok tool inventory diagnostic helper: already applied")


# ---------------------------------------------------------------------------
# 2. One-line module registration in upstream mapper/mod.rs.
# ---------------------------------------------------------------------------
mod_text = MAPPER_MOD.read_text(encoding="utf-8")
mod_line = "pub(crate) mod sub2api_grok_compat;\n"
if mod_line not in mod_text:
    anchor = "pub(crate) mod responses;\n"
    if anchor not in mod_text:
        raise SystemExit("missing anchor: mapper responses module declaration")
    mod_text = mod_text.replace(anchor, anchor + f"{HOOK}\n" + mod_line, 1)
    print("[ok] mapper module hook: applied")
else:
    print("[ok] mapper module hook: already applied")
MAPPER_MOD.write_text(mod_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# 3. Thin hooks in upstream responses.rs.
#    IMPORTANT: detect hooks by semantic call markers, not complete source lines.
#    rustfmt may wrap assignments across lines; line-based detection is not
#    idempotent after formatting.
# ---------------------------------------------------------------------------
text = RESPONSES.read_text(encoding="utf-8")

# Migrate the earlier inline implementation if a user upgrades from the first
# compat build instead of starting from pristine upstream.
legacy_start = text.find(
    "/// Enable the Grok Responses compatibility shim for a normal bearer provider"
)
impl_anchor = "impl RequestMapper for ResponsesPassthroughMapper {\n"
if legacy_start >= 0:
    impl_pos = text.find(impl_anchor, legacy_start)
    if impl_pos < 0:
        raise SystemExit("legacy inline helper found but RequestMapper anchor missing")
    text = text[:legacy_start] + text[impl_pos:]
    print("[ok] migrated legacy inline helpers out of responses.rs")

text = remove_rust_module(text, "#[cfg(test)]\nmod sub2api_grok_compat_tests {")

# ---- request model gate ----------------------------------------------------
legacy_request_assignment = (
    "let use_grok_compat = should_use_grok_compat(provider, &body);"
)
qualified_request_call = (
    "crate::mapper::sub2api_grok_compat::should_use_grok_compat(provider, &body)"
)
qualified_request_assignment = f"let use_grok_compat = {qualified_request_call};"

if legacy_request_assignment in text:
    text = text.replace(
        legacy_request_assignment, qualified_request_assignment, 1
    )
    print("[ok] request model gate: migrated legacy call")
elif qualified_request_call not in text:
    impl_pos = text.find(impl_anchor)
    if impl_pos < 0:
        raise SystemExit("missing anchor: RequestMapper impl")
    sig = "    ) -> Result<RequestPlan, AdapterError> {\n"
    sig_pos = text.find(sig, impl_pos)
    if sig_pos < 0:
        raise SystemExit("missing anchor: Responses map_request signature")
    insert_at = sig_pos + len(sig)
    text = (
        text[:insert_at]
        + f"        {HOOK}\n"
        + f"        {qualified_request_assignment}\n"
        + text[insert_at:]
    )
    print("[ok] request model gate: applied")
else:
    print("[ok] request model gate: already applied")

# Remove any stale unqualified assignment left by a legacy migration.
text = re.sub(
    r"(?m)^[ \t]*let use_grok_compat = should_use_grok_compat\(provider, &body\);[ \t]*\n?",
    "",
    text,
)
# And repair branches that were hit by the old rustfmt-sensitive patcher.
request_assignment_re = re.compile(
    r"(?m)^[ \t]*let use_grok_compat\s*=\s*(?:\n[ \t]*)?"
    r"crate::mapper::sub2api_grok_compat::should_use_grok_compat"
    r"\(provider,\s*&body\);[ \t]*\n?"
)
text = dedupe_regex(text, request_assignment_re, "request model gate")

# ---- request-side tool inventory diagnostic -------------------------------
def tool_diag_re(stage: str) -> re.Pattern[str]:
    return re.compile(
        r"(?ms)^[ \t]*crate::mapper::sub2api_grok_compat::"
        r"log_sub2api_grok_tool_inventory\s*\(\s*\""
        + re.escape(stage)
        + r"\"\s*,\s*&body\s*,\s*provider\s*,?\s*\);[ \t]*\n?"
    )


inbound_diag_re = tool_diag_re("inbound")
if not inbound_diag_re.search(text):
    match = request_assignment_re.search(text)
    if not match:
        raise SystemExit("missing anchor: request model gate for inbound tool diagnostic")
    call = (
        f"        {HOOK}\n"
        "        crate::mapper::sub2api_grok_compat::log_sub2api_grok_tool_inventory(\n"
        "            \"inbound\", &body, provider,\n"
        "        );\n"
    )
    text = text[: match.end()] + call + text[match.end() :]
    print("[ok] inbound Grok tool inventory diagnostic: applied")
else:
    print("[ok] inbound Grok tool inventory diagnostic: already applied")
text = dedupe_regex(text, inbound_diag_re, "inbound Grok tool inventory diagnostic")

# ---- local compaction gate -------------------------------------------------
old = "if crate::mapper::grok_build::responses_upstream_lacks_compaction(provider) {"
new = (
    "if crate::mapper::grok_build::responses_upstream_lacks_compaction(provider)\n"
    "            || use_grok_compat\n"
    "        {"
)
if old in text:
    text = text.replace(old, new, 1)
elif "responses_upstream_lacks_compaction(provider)" not in text or "|| use_grok_compat" not in text:
    raise SystemExit("missing anchor: Grok compaction gate")

# ---- request-side Grok shim context + body adapter -------------------------
old = "let grok_shim_ctx = if crate::mapper::grok_build::is_grok_build_provider(provider) {"
new = "let grok_shim_ctx = if use_grok_compat {"
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("missing anchor: request shim context gate")

old = "let body = if crate::mapper::grok_build::is_grok_build_provider(provider) {"
new = "let body = if use_grok_compat {"
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("missing anchor: request Grok adapter gate")

# ---- optional Grok Free cache companion -----------------------------------
cache_call_marker = (
    "crate::mapper::sub2api_grok_compat::apply_sub2api_grok_free_cache_compat"
)
cache_assignment = (
    "        let body = crate::mapper::sub2api_grok_compat::"
    "apply_sub2api_grok_free_cache_compat(body, provider);\n"
)
if cache_call_marker not in text:
    old_call = "        let body = apply_sub2api_grok_free_cache_compat(body, provider);\n"
    if old_call in text:
        text = text.replace(old_call, f"        {HOOK}\n" + cache_assignment, 1)
    else:
        observe_comment = "        // [MOC-234] 只读观测整合"
        idx_comment = text.find(observe_comment)
        if idx_comment < 0:
            raise SystemExit("missing anchor: observe comment after Grok body adapter")
        before = text[:idx_comment]
        block_end = before.rfind("        };\n\n")
        if block_end < 0:
            raise SystemExit("missing anchor: Grok body adapter closing block")
        insert_at = block_end + len("        };\n")
        text = text[:insert_at] + f"        {HOOK}\n" + cache_assignment + text[insert_at:]
    print("[ok] Free cache body routing: applied")
else:
    print("[ok] Free cache body routing: already applied")

cache_assignment_re = re.compile(
    r"(?m)^[ \t]*let body\s*=\s*"
    r"crate::mapper::sub2api_grok_compat::apply_sub2api_grok_free_cache_compat"
    r"\(\s*body\s*,\s*provider\s*,?\s*\);[ \t]*\n?"
)
text = dedupe_regex(text, cache_assignment_re, "Free cache body routing")

# ---- final outbound tool inventory diagnostic ------------------------------
outbound_diag_re = tool_diag_re("outbound")
if not outbound_diag_re.search(text):
    match = cache_assignment_re.search(text)
    if not match:
        raise SystemExit("missing anchor: cache routing for outbound tool diagnostic")
    call = (
        f"        {HOOK}\n"
        "        crate::mapper::sub2api_grok_compat::log_sub2api_grok_tool_inventory(\n"
        "            \"outbound\", &body, provider,\n"
        "        );\n"
    )
    text = text[: match.end()] + call + text[match.end() :]
    print("[ok] outbound Grok tool inventory diagnostic: applied")
else:
    print("[ok] outbound Grok tool inventory diagnostic: already applied")
text = dedupe_regex(text, outbound_diag_re, "outbound Grok tool inventory diagnostic")

# ---- response-side tool-call shim gate ------------------------------------
response_call_marker = (
    "crate::mapper::sub2api_grok_compat::should_use_grok_compat"
    "(provider, &request_plan.body)"
)
legacy_response_gate = "if should_use_grok_compat(provider, &request_plan.body) {"
upstream_response_gate = (
    "if crate::mapper::grok_build::is_grok_build_provider(provider) {"
)
qualified_response_gate = f"if {response_call_marker} {{"

if legacy_response_gate in text:
    text = text.replace(legacy_response_gate, qualified_response_gate, 1)
elif response_call_marker in text:
    pass
elif upstream_response_gate in text:
    text = text.replace(upstream_response_gate, qualified_response_gate, 1)
else:
    raise SystemExit("missing anchor: response Grok shim gate")

RESPONSES.write_text(text, encoding="utf-8")
print(f"[ok] thin responses hooks refreshed: {RESPONSES}")
