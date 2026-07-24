from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")
    print(f"updated {path}")


def replace_required(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        print(f"already updated {path}")
        return
    if old not in text:
        raise SystemExit(f"required anchor missing in {path}: {old!r}")
    write(path, text.replace(old, new, 1))


# r3: the visible card must use the exact same source-of-truth as the
# highlighted Responses segment. Do not route this through another computed.
path = "frontend/src/components/provider/ProviderFormModal.vue"
text = read(path)
text = text.replace(
    "// 所有 Responses provider 都显示兼容卡片，避免 preset/custom 分类变化把 UI 隐藏。\n"
    "// 真正请求侧仍会按 provider 开关 + model=grok/grok-*/grok/* 双重 gate，\n"
    "// 所以 Luna/GPT 以及未开启开关的 Responses provider 仍保持原生直透。\n"
    "const showSub2apiGrokCompat = computed(() => form.apiFormat === 'responses')\n",
    "",
)
text = text.replace(
    'v-if="showSub2apiGrokCompat"',
    'v-if="form.apiFormat === \'responses\'"',
)
if 'v-if="form.apiFormat === \'responses\'"' not in text:
    raise SystemExit("direct Responses compat-card condition was not installed")
write(path, text)

# Unique installable revision. Tauri uses this value for the application bundle.
replace_required(
    "src-tauri/tauri.conf.json",
    '"version": "2.4.5+2"',
    '"version": "2.4.5+3"',
)
replace_required(
    "src-tauri/tauri.conf.json",
    '"title": "Codex App Transfer — Sub2API Grok Compat r2 — v2.4.5+2"',
    '"title": "Codex App Transfer — Sub2API Grok Compat r3 — v2.4.5+3"',
)

# Keep macOS/custom titlebar and visible top badge unambiguous too.
replace_required(
    "frontend/src/layout/AppLayout.vue",
    "Codex App Transfer — Sub2API Grok Compat r2 — v2.4.5+2",
    "Codex App Transfer — Sub2API Grok Compat r3 — v2.4.5+3",
)
replace_required(
    "frontend/src/i18n/zh.ts",
    '"compat.buildBadge": "Sub2API Grok Compat r2 · v2.4.5+2"',
    '"compat.buildBadge": "Sub2API Grok Compat r3 · v2.4.5+3"',
)
replace_required(
    "frontend/src/i18n/en.ts",
    '"compat.buildBadge": "Sub2API Grok Compat r2 · v2.4.5+2"',
    '"compat.buildBadge": "Sub2API Grok Compat r3 · v2.4.5+3"',
)

print("Sub2API Grok Compat r3 patch applied successfully")
