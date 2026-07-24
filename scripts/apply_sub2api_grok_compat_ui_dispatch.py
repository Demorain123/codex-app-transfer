from pathlib import Path
import runpy

LEGACY_PATCHER = Path("scripts/apply_sub2api_grok_compat_ui.py")


def contains(path: str, *needles: str) -> bool:
    p = Path(path)
    if not p.is_file():
        return False
    text = p.read_text(encoding="utf-8")
    return all(needle in text for needle in needles)


def overlay_complete() -> bool:
    """Semantic, formatting-insensitive completeness check for the UI/backend overlay."""
    return all(
        [
            Path("frontend/src/components/provider/Sub2ApiGrokCompatControls.vue").is_file(),
            contains(
                "src-tauri/src/admin/handlers/providers/crud.rs",
                "pub sub2api_grok_compat: Option<bool>",
                "pub sub2api_grok_free_cache_compat: Option<bool>",
                '"sub2apiGrokCompat".into()',
                '"sub2apiGrokFreeCacheCompat".into()',
                "input.sub2api_grok_compat",
                "input.sub2api_grok_free_cache_compat",
            ),
            contains(
                "frontend/src/api/types.ts",
                "sub2apiGrokCompat?: boolean",
                "sub2apiGrokFreeCacheCompat?: boolean",
            ),
            contains(
                "frontend/src/api/providers.ts",
                "sub2apiGrokCompat: !!provider.sub2apiGrokCompat",
                "sub2apiGrokFreeCacheCompat: !!provider.sub2apiGrokFreeCacheCompat",
                "sub2apiGrokCompat: !!payload.sub2apiGrokCompat",
                "sub2apiGrokFreeCacheCompat: !!payload.sub2apiGrokFreeCacheCompat",
            ),
            contains(
                "frontend/src/components/provider/ProviderFormModal.vue",
                "Sub2ApiGrokCompatControls",
                'v-model:enabled="form.sub2apiGrokCompat"',
                'v-model:cache-enabled="form.sub2apiGrokFreeCacheCompat"',
            ),
            contains(
                "frontend/src/layout/TopTabBar.vue",
                "compat-build-badge",
                "compat.buildBadge",
            ),
            contains(
                "frontend/src/layout/AppLayout.vue",
                "Codex App Transfer — Sub2API Grok Compat",
            ),
            # Match the stable title prefix, not the full value: revision overlay
            # appends `rN — vX.Y.Z+N` so exact old-title checks become stale.
            contains(
                "src-tauri/tauri.conf.json",
                "Codex App Transfer — Sub2API Grok Compat",
            ),
            contains(
                "frontend/src/i18n/zh.ts",
                '"compat.buildBadge"',
                '"providerForm.grokCompat"',
                '"providerForm.grokFreeCacheCompat"',
            ),
            contains(
                "frontend/src/i18n/en.ts",
                '"compat.buildBadge"',
                '"providerForm.grokCompat"',
                '"providerForm.grokFreeCacheCompat"',
            ),
        ]
    )


if overlay_complete():
    print("[ok] Sub2API Grok UI/backend overlay already complete; no-op")
else:
    if not LEGACY_PATCHER.is_file():
        raise SystemExit(f"missing first-install UI patcher: {LEGACY_PATCHER}")
    print("[info] UI/backend overlay incomplete; running first-install patcher")
    runpy.run_path(str(LEGACY_PATCHER), run_name="__main__")
    if not overlay_complete():
        raise SystemExit(
            "UI/backend patcher exited without producing a complete overlay; "
            "upstream source likely changed and needs a reviewed anchor update"
        )
    print("[ok] Sub2API Grok UI/backend overlay installed and verified")
