from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKER = "CAS-R38-MODEL-ROUTE-OBSERVABILITY"


def load(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r38 required file missing: {rel}")
    return path.read_text(encoding="utf-8")


def save(rel: str, body: str) -> None:
    (ROOT / rel).write_text(body, encoding="utf-8")


def replace_once(body: str, old: str, new: str, label: str) -> str:
    count = body.count(old)
    if count != 1:
        raise SystemExit(f"r38 anchor count {count}, expected 1: {label}")
    return body.replace(old, new, 1)


rel = "crates/proxy/src/telemetry.rs"
body = load(rel)
if MARKER not in body:
    body = body.replace(
        "// CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n",
        "// CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD\n// CAS-R38-MODEL-ROUTE-OBSERVABILITY\n",
        1,
    )
    body = replace_once(
        body,
        "    pub request_bytes: u64,\n    // CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD",
        "    pub request_bytes: u64,\n"
        "    // CAS-R38-MODEL-ROUTE-OBSERVABILITY\n"
        "    pub request_kind: Option<String>,\n"
        "    pub tool_count: u32,\n"
        "    pub duplicate_tool_names: Vec<String>,\n"
        "    pub input_image_count: u32,\n"
        "    // CAS-R37-FAULT-ATTRIBUTION-QUOTA-GUARD",
        "lifecycle request-shape fields",
    )
    body = replace_once(
        body,
        "        model: impl Into<String>,\n        request_bytes: u64,\n    ) -> u64 {",
        "        model: impl Into<String>,\n"
        "        request_bytes: u64,\n"
        "        request_kind: Option<String>,\n"
        "        tool_count: u32,\n"
        "        duplicate_tool_names: Vec<String>,\n"
        "        input_image_count: u32,\n"
        "    ) -> u64 {",
        "lifecycle start signature",
    )
    body = replace_once(
        body,
        "            request_bytes,\n            quota_primary_used_percent: None,",
        "            request_bytes,\n"
        "            request_kind,\n"
        "            tool_count,\n"
        "            duplicate_tool_names,\n"
        "            input_image_count,\n"
        "            quota_primary_used_percent: None,",
        "lifecycle request-shape initialization",
    )
    save(rel, body)


rel = "crates/proxy/src/forward.rs"
body = load(rel)
if MARKER not in body:
    body = replace_once(
        body,
        "use thiserror::Error;\n",
        "use thiserror::Error;\nuse serde::Deserialize;\n",
        "serde deserialize import",
    )
    insert_after = 'const DEFAULT_OUTBOUND_USER_AGENT: &str = concat!("Codex-App-Transfer/", env!("CARGO_PKG_VERSION"));\n'
    helper = r'''

// CAS-R38-MODEL-ROUTE-OBSERVABILITY
#[derive(Debug, Default)]
struct RequestShapeR38 {
    request_kind: Option<String>,
    tool_count: u32,
    duplicate_tool_names: Vec<String>,
    input_image_count: u32,
}

#[derive(Debug, Deserialize, Default)]
struct RequestEnvelopeR38 {
    #[serde(default)]
    tools: Vec<RequestToolR38>,
    #[serde(default)]
    input: Vec<RequestInputR38>,
}

#[derive(Debug, Deserialize, Default)]
struct RequestInputR38 {
    #[serde(rename = "type", default)]
    kind: String,
    #[serde(default)]
    tools: Vec<RequestToolR38>,
    #[serde(default)]
    content: Vec<RequestInputR38>,
}

#[derive(Debug, Deserialize, Default)]
struct RequestToolR38 {
    #[serde(rename = "type", default)]
    kind: String,
    #[serde(default)]
    name: String,
    #[serde(default)]
    tools: Vec<RequestToolR38>,
    #[serde(default)]
    children: Vec<RequestToolR38>,
}

#[derive(Debug, Deserialize, Default)]
struct TurnMetadataR38 {
    #[serde(default)]
    request_kind: Option<String>,
}

fn collect_tool_names_r38(tool: &RequestToolR38, namespace: Option<&str>, names: &mut Vec<String>) {
    let kind = tool.kind.trim();
    let name = tool.name.trim();
    if matches!(kind, "function" | "custom") && !name.is_empty() {
        let normalized = match namespace {
            Some(ns) if !ns.is_empty() => format!("{ns}::{name}"),
            _ => name.to_owned(),
        };
        names.push(normalized);
    }
    if kind == "namespace" && !name.is_empty() {
        for child in tool.tools.iter().chain(tool.children.iter()) {
            collect_tool_names_r38(child, Some(name), names);
        }
    }
}

fn collect_input_shape_r38(item: &RequestInputR38, names: &mut Vec<String>, image_count: &mut u32) {
    if item.kind == "input_image" {
        *image_count = image_count.saturating_add(1);
    }
    for tool in &item.tools {
        collect_tool_names_r38(tool, None, names);
    }
    for child in &item.content {
        collect_input_shape_r38(child, names, image_count);
    }
}

fn request_shape_r38(headers: &HeaderMap, body: &[u8]) -> RequestShapeR38 {
    let request_kind = headers
        .get("x-codex-turn-metadata")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| serde_json::from_str::<TurnMetadataR38>(value).ok())
        .and_then(|meta| meta.request_kind)
        .map(|value| value.chars().take(40).collect::<String>());

    let Ok(envelope) = serde_json::from_slice::<RequestEnvelopeR38>(body) else {
        return RequestShapeR38 { request_kind, ..Default::default() };
    };
    let mut names = Vec::new();
    for tool in &envelope.tools {
        collect_tool_names_r38(tool, None, &mut names);
    }
    let mut input_image_count = 0u32;
    for item in &envelope.input {
        collect_input_shape_r38(item, &mut names, &mut input_image_count);
    }
    let mut counts = std::collections::BTreeMap::<String, u32>::new();
    for name in &names {
        *counts.entry(name.clone()).or_default() += 1;
    }
    let duplicate_tool_names = counts
        .into_iter()
        .filter_map(|(name, count)| (count > 1).then_some(name))
        .take(8)
        .collect();
    RequestShapeR38 {
        request_kind,
        tool_count: names.len().min(u32::MAX as usize) as u32,
        duplicate_tool_names,
        input_image_count,
    }
}
'''
    body = replace_once(body, insert_after, insert_after + helper, "r38 request shape helper")
    old_call = '''    let lifecycle_id = telemetry.lifecycles.start(
        request_lifecycle_correlation_r34(&parts.headers),
        resolved.provider.id.clone(),
        retry_runtime_diag_model.unwrap_or("<unknown>").to_owned(),
        plan.body.len() as u64,
    );
'''
    new_call = '''    // CAS-R38-MODEL-ROUTE-OBSERVABILITY: shape-only metadata for per-model diagnosis.
    let request_shape_r38 = request_shape_r38(&parts.headers, &plan.body);
    let lifecycle_id = telemetry.lifecycles.start(
        request_lifecycle_correlation_r34(&parts.headers),
        resolved.provider.id.clone(),
        retry_runtime_diag_model.unwrap_or("<unknown>").to_owned(),
        plan.body.len() as u64,
        request_shape_r38.request_kind,
        request_shape_r38.tool_count,
        request_shape_r38.duplicate_tool_names,
        request_shape_r38.input_image_count,
    );
'''
    body = replace_once(body, old_call, new_call, "lifecycle call")
    save(rel, body)

print("r38 proxy observability: COMPLETE")
