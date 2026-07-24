from pathlib import Path
import re

RESPONSES = Path("crates/adapters/src/mapper/responses.rs")
MAPPER_MOD = Path("crates/adapters/src/mapper/mod.rs")
COMPAT = Path("crates/adapters/src/mapper/sub2api_grok_compat.rs")
COMPAT_TEMPLATE = Path("scripts/sub2api_grok_compat_overlay.rs")
HOOK = "// CAS-SUB2API-GROK-COMPAT-HOOK"


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
