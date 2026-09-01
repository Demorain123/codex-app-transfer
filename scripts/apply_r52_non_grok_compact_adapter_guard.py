from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESPONSES = ROOT / "crates/adapters/src/mapper/responses.rs"
MARKER = "CAS-R52-NON-GROK-COMPACT-ADAPTER-GUARD"

text = RESPONSES.read_text(encoding="utf-8")
if MARKER in text:
    print("r52 non-Grok compact adapter guard already applied")
    raise SystemExit(0)

old = '''                // 套 grok_build 适配(tools/reasoning 归一),让摘要请求也被 grok 接受
                let summ =
                    crate::mapper::grok_build::adapt_grok_build_request_body(&summ, provider)
                        .unwrap_or(summ);
'''
new = r'''                // CAS-R52-NON-GROK-COMPACT-ADAPTER-GUARD
                // Only Grok compact requests may use Grok's tool/reasoning normalizer.
                // r52 also locally implements Codex private compaction for GPT/Luna on
                // an opted-in mixed Sub2API provider; those models must keep the native
                // Responses summary body untouched. Applying the Grok adapter to Luna
                // would rewrite reasoning/tool semantics even though the ordinary Luna
                // /responses path is native passthrough.
                let summ = if use_grok_compat
                    || crate::mapper::grok_build::responses_upstream_lacks_compaction(provider)
                {
                    crate::mapper::grok_build::adapt_grok_build_request_body(&summ, provider)
                        .unwrap_or(summ)
                } else {
                    summ
                };
'''
if old not in text:
    raise SystemExit("r52 non-Grok compact adapter guard anchor missing")
text = text.replace(old, new, 1)

for invariant in (
    MARKER,
    "let summ = if use_grok_compat",
    "responses_upstream_lacks_compaction(provider)",
    "those models must keep the native",
):
    if invariant not in text:
        raise SystemExit(f"r52 non-Grok compact guard invariant missing: {invariant}")

RESPONSES.write_text(text, encoding="utf-8")
print("R52 NON-GROK COMPACT ADAPTER GUARD PASS")
print("- Grok compaction keeps grok_build normalization")
print("- Sub2API GPT/Luna local compaction keeps native Responses request semantics")
