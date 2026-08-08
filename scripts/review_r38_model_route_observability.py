from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

required = {
    "crates/proxy/src/telemetry.rs": [
        "CAS-R38-MODEL-ROUTE-OBSERVABILITY",
        "pub request_kind: Option<String>",
        "pub tool_count: u32",
        "pub duplicate_tool_names: Vec<String>",
        "pub input_image_count: u32",
    ],
    "crates/proxy/src/forward.rs": [
        "struct RequestShapeR38",
        "fn request_shape_r38",
        "request_shape_r38.duplicate_tool_names",
        "request_shape_r38.input_image_count",
    ],
    "src-tauri/src/admin/handlers/chain_health.rs": [
        "struct ModelRouteHealth",
        "model_routes: Vec<ModelRouteHealth>",
        "fn model_routes_r38()",
        "fault_duplicate_tool_schema",
        "fault_large_context",
        "fault_recovered_session",
        "refresh_healthy_transfer",
        "核心模型链路当前可用",
    ],
    "frontend/src/api/chainHealth.ts": [
        "export interface ModelRouteHealth",
        "modelRoutes: ModelRouteHealth[]",
    ],
    "frontend/src/pages/ProxyPage.vue": [
        "chainHealth.modelRoutes",
        "route.duplicateToolNames",
        "formatRouteBytes",
    ],
    "frontend/src/i18n/zh.ts": [
        '"chainHealth.modelRoutes": "模型路径"',
        "Sub2API Grok Compat r38",
    ],
    "frontend/src/i18n/en.ts": [
        '"chainHealth.modelRoutes": "Model routes"',
        "Sub2API Grok Compat r38",
    ],
}

for rel, markers in required.items():
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"r38 review missing file: {rel}")
    text = path.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in text:
            raise SystemExit(f"r38 review missing marker in {rel}: {marker}")

version = (ROOT / "SUB2API_GROK_COMPAT_VERSION.txt").read_text(encoding="utf-8")
if "compat_revision=38" not in version or "app_version=2.4.5+38" not in version:
    raise SystemExit("r38 review: wrong version stamp")

health = (ROOT / "src-tauri/src/admin/handlers/chain_health.rs").read_text(encoding="utf-8")
if 'actions.push(recover_transfer(&state, &before, true).await);' in health:
    raise SystemExit("r38 review: blind Transfer refresh still exists in upstream backend recovery")
if "request形态诊断只保留" in health:
    raise SystemExit("r38 review: unexpected mixed-language privacy marker")

print("r38 model-route observability review: PASS")
