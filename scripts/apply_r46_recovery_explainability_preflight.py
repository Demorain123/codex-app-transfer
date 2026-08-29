from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "frontend/src/pages/ProxyPage.vue"
DONE = "CAS-R46-RECOVERY-EXPLAINABILITY-UI"
MARKER = "CAS-R46-RECOVERY-EXPLAINABILITY-PREFLIGHT"

text = PAGE.read_text(encoding="utf-8")
if DONE in text:
    print("r46 recovery explainability preflight: final UI already present")
    raise SystemExit(0)


def canonicalize_button(click_expr: str, canonical: str, label: str) -> None:
    global text
    needle = f'@click="{click_expr}"'
    positions = []
    start = 0
    while True:
        idx = text.find(needle, start)
        if idx < 0:
            break
        positions.append(idx)
        start = idx + len(needle)
    if len(positions) != 1:
        raise SystemExit(
            f"r46 recovery explainability preflight: expected one {label} click target, found {len(positions)}"
        )
    idx = positions[0]
    begin = text.rfind("          <button", 0, idx)
    if begin < 0:
        begin = text.rfind("<button", 0, idx)
    end = text.find("</button>", idx)
    if begin < 0 or end < 0:
        raise SystemExit(f"r46 recovery explainability preflight: cannot bound {label} button")
    end += len("</button>")
    if text[end:end + 2] == "\r\n":
        end += 2
    elif text[end:end + 1] == "\n":
        end += 1
    text = text[:begin] + canonical + text[end:]


# r36/r46 overlays own these two controls. Later replay formatting may alter whitespace
# or attributes, but explainability only needs the semantic click targets. Canonicalize
# those two superseded button blocks immediately before the r46 explainability transform.
canonicalize_button(
    "onRecoverChain",
    '''          <button
            class="chain-health__button chain-health__button--repair"
            :disabled="chainRecovering"
            @click="onRecoverChain"
          >
            <IconWrench :class="{ 'is-spinning': chainRecovering }" />
            {{ t('chainHealth.recover') }}
          </button>
''',
    "chain repair",
)

canonicalize_button(
    "openThreadRecovery",
    '''          <button
            class="chain-health__button chain-health__button--thread-recovery"
            :disabled="threadRecoveryRunning"
            @click="openThreadRecovery"
          >
            <IconRotateCcw :class="{ 'is-spinning': threadRecoveryRunning }" />
            旧会话恢复
          </button>
''',
    "old-thread recovery",
)

if MARKER not in text:
    anchor = "// CAS-R46-MODEL-SWITCH-OLD-THREAD-RECOVERY-UI\n"
    if anchor not in text:
        raise SystemExit("r46 recovery explainability preflight: r46 UI marker missing")
    text = text.replace(anchor, anchor + f"// {MARKER}\n", 1)

PAGE.write_text(text, encoding="utf-8")
print("R46 RECOVERY EXPLAINABILITY PREFLIGHT PASS")
