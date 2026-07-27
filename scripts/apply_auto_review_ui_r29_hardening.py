from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "scripts/apply_auto_review_ui_r29.py"

text = GEN.read_text(encoding="utf-8")
marker = "CAS-AUTO-REVIEW-UI-R29-UNIQUE-SUCCESS-ANCHOR"

if marker not in text:
    old = '''    parent = replace_once(
        parent,
        "    toast(tFmt('providerForm.modelsFetched', { count: availableModels.value.length }))\\n",
        "    if (!silent) toast(tFmt('providerForm.modelsFetched', { count: availableModels.value.length }))\\n",
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
    GEN.write_text(text, encoding="utf-8")
    print("r29 hardened fetchModels success-toast generator anchor")
else:
    print("r29 fetchModels generator anchor already hardened")

# Fail closed: the old globally-ambiguous replacement must no longer be present.
text = GEN.read_text(encoding="utf-8")
if marker not in text:
    raise SystemExit("r29 hardening marker missing after generator patch")
if '''        "    toast(tFmt('providerForm.modelsFetched', { count: availableModels.value.length }))\\n",
        "    if (!silent) toast''' in text:
    raise SystemExit("r29 ambiguous bare success-toast generator anchor still present")

print("r29 generator hardening: PASS")
