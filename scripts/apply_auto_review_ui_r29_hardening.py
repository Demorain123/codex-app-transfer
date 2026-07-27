from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "scripts/apply_auto_review_ui_r29.py"

text = GEN.read_text(encoding="utf-8")
anchor_marker = "CAS-AUTO-REVIEW-UI-R29-UNIQUE-SUCCESS-ANCHOR"

# The r27 fetchModels function has the same success toast in its normal and fallback branches.
# Harden the generator to anchor the normal one together with the following catch boundary.
if anchor_marker not in text:
    # Match the generator source as it exists on disk: the original replacement strings do not
    # themselves include a trailing \n. We replace that generator block with a contextual one.
    old = '''    parent = replace_once(
        parent,
        "    toast(tFmt('providerForm.modelsFetched', { count: availableModels.value.length }))",
        "    if (!silent) toast(tFmt('providerForm.modelsFetched', { count: availableModels.value.length }))",
        "silent fetch success toast",
    )
'''
    new = '''    # CAS-AUTO-REVIEW-UI-R29-UNIQUE-SUCCESS-ANCHOR: the r27 function contains the
    # same toast in both the normal-success and fallback-success branches. Anchor the normal one
    # together with the following catch boundary instead of pretending the toast text is unique.
    parent = replace_once(
        parent,
        "    toast(tFmt('providerForm.modelsFetched', { count: availableModels.value.length }))\\n"
        "  } catch (e) {",
        "    if (!silent) toast(tFmt('providerForm.modelsFetched', { count: availableModels.value.length }))\\n"
        "  } catch (e) {",
        "silent fetch success toast",
    )
'''
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"r29 hardening: expected one generator success-toast block, found {count}")
    text = text.replace(old, new, 1)
    print("r29 hardened fetchModels success-toast generator anchor")

# Opening Edit should refresh only the model list. The existing fetchModels implementation also
# auto-fills backend `suggested` values into empty model slots; doing that from a silent automatic
# refresh would make merely opening the modal mutate provider configuration. Add a generator patch
# that keeps suggested-slot filling manual-only.
suggest_marker = "CAS-AUTO-REVIEW-UI-R29-SILENT-NO-SUGGEST"
if suggest_marker not in text:
    insertion_anchor = '''    parent = replace_once(
        parent,
        "  form.apiKey = secret.apiKey || ''\\n",
'''
    if text.count(insertion_anchor) != 1:
        raise SystemExit(
            f"r29 hardening: expected one apiKey generator anchor, found {text.count(insertion_anchor)}"
        )
    patch_block = '''    parent = replace_once(
        parent,
        "    const suggested = res.suggested || {}\\n"
        "    const valid = new Set(availableModels.value.map((o) => o.value))\\n"
        "    for (const slot of Object.keys(form.models)) {\\n"
        "      const sv = suggested[slot]\\n"
        "      if (sv && !form.models[slot] && valid.has(sv)) form.models[slot] = sv\\n"
        "    }",
        "    if (!silent) { // CAS-AUTO-REVIEW-UI-R29-SILENT-NO-SUGGEST\\n"
        "      const suggested = res.suggested || {}\\n"
        "      const valid = new Set(availableModels.value.map((o) => o.value))\\n"
        "      for (const slot of Object.keys(form.models)) {\\n"
        "        const sv = suggested[slot]\\n"
        "        if (sv && !form.models[slot] && valid.has(sv)) form.models[slot] = sv\\n"
        "      }\\n"
        "    }",
        "silent refresh must not mutate model slots",
    )
'''
    text = text.replace(insertion_anchor, patch_block + insertion_anchor, 1)
    print("r29 hardened silent refresh against suggested-slot mutation")

GEN.write_text(text, encoding="utf-8")

# Fail closed: both hardenings must be durable in the generator and the ambiguous old bare block gone.
text = GEN.read_text(encoding="utf-8")
for marker in (anchor_marker, suggest_marker):
    if marker not in text:
        raise SystemExit(f"r29 hardening marker missing after generator patch: {marker}")
if '''        "    toast(tFmt('providerForm.modelsFetched', { count: availableModels.value.length }))",
        "    if (!silent) toast''' in text:
    raise SystemExit("r29 ambiguous bare success-toast generator anchor still present")

print("r29 generator hardening: PASS")
