# r32 No Lagging

r32 is a narrow Windows stability layer on top of the validated r31 stack.

It does **not** replace r24-r31 routing, provider/auth, catalog, Auto Review, Hybrid Direct, runtime diagnostics, or proxy lifecycle behavior.

## Why r32 exists

The earlier No Micro experiment was built around the Windows Codex Micro / Work Louder path:

```text
@worklouder/device-kit-oai
  -> Work Louder device stack
     -> serialport / native device modules
```

The original controlled A/B and later public Windows reports show that this optional hardware integration can create severe UI lag even when the user does not own the hardware.

Newer evidence also matters: some 26.715 builds no longer expose the old `serialport.node` failure but can still block in HID/accessory enumeration (`HID.node -> hid.dll`). Therefore r32 no longer treats the string `serialport` as a required compatibility signal. The reviewed interception boundary remains the top-level `@worklouder/device-kit-oai` module.

Separately, long-running Codex/subagent workloads can accumulate MCP/helper process stacks. Public reproductions show subagents starting additional stdio MCP stacks and incomplete cleanup after `close_agent`. The user's own long-run captures also showed very large MCP/helper counts and memory use.

## r32 behavior

### A: Normal

Keeps the exact legacy Restart Codex App control path with the accessory integration untouched.

### B: No Lagging

Uses the same restart/config preparation as A, then:

1. runs the existing r23 worker-safe inspector launcher;
2. intercepts **only** `@worklouder/device-kit-oai`;
3. preserves the old `__CODEX_MICRO_DISABLED_LOCAL__` marker and Worker `execArgv` hardening;
4. starts the r32 MCP Exit Guard before Codex starts, so the generation can be observed from the beginning.

The canonical A/B log mode for B is now:

```text
mode=no-lagging
```

The backend still accepts `mode=no-micro` as a compatibility alias.

## MCP Exit Guard

The guard is a hidden PowerShell watcher written from the embedded r32 resource.

It is intentionally conservative:

- exact Codex Desktop executable path is supplied by Transfer;
- helper candidates are tracked only while they have a provable ancestor in that Desktop generation;
- PID and process start time are saved as identity evidence;
- no process command line is read or logged;
- no prompt, token, auth value, or thread content is read;
- no `taskkill /IM node.exe` or process-name-wide kill is used;
- no helper is terminated while the exact Codex Desktop executable is still running;
- Desktop reappearance cancels cleanup;
- cleanup uses exact PID + start-time identity and processes deeper descendants first;
- a named per-user mutex prevents duplicate watchers.

The guard log is intentionally minimal:

```text
%LOCALAPPDATA%\CodexMcpJanitorR32\events.jsonl
```

## What r32 does not claim to fix

No Lagging is not a universal Codex crash fix. It does not claim to solve:

- HTTP 429/502/503;
- remote compaction failures;
- `agent loop died unexpectedly`;
- `unknown conversation` / damaged thread state;
- upstream provider failures;
- arbitrary third-party Hook bugs.

Those remain separate diagnostic domains.

## High-concurrency requirement

r32 explicitly preserves the user's workflow:

- no configured MCP-count limit;
- no subagent-count limit added by Transfer;
- no running MCP is killed because memory/process count is high;
- exit cleanup is a lifecycle workaround, not workload throttling.

## Evidence incorporated

Public reports / related work reviewed for r32 include:

- openai/codex #33409 — Windows hangs after Codex Micro gate activation; controlled same-build A/B by disabling the gate;
- openai/codex #33518 — repeated `serialport.node` background crashes causing 2-5 second UI freezes;
- openai/codex #33780 — newer HID/native enumeration can block the Electron main thread;
- openai/codex #25015 — subagent MCP stacks persist and grow roughly linearly;
- LostFrxks/codex-mcp-clean — snapshot/report/cleanup only the MCP subtrees attributable to the selected Codex app-server;
- Chromium's use of Windows Job Objects with `KILL_ON_JOB_CLOSE` is a useful upstream design reference for future native containment, but r32 does not assign Codex to a new Job Object because that could change upstream process semantics.

User-provided evidence also remains part of the design input:

- original `codex-no-micro` launcher and A/B logs;
- long-run Codex Health Monitor captures;
- MCP process/memory accumulation;
- `goal_memory.py` orphan research;
- Health Monitor vNext research;
- MCP Janitor v3 Auto design.

## Version

Visible/package revision:

```text
r32 / v2.4.5+32
```

Keep the PR Draft until Windows package CI passes and a real-device A/B confirms that:

1. No Lagging injects successfully on the user's patched Codex build;
2. normal MCP/subagent operation is unchanged while Codex is running;
3. after a true Codex Desktop exit, residual helpers are reduced without touching unrelated processes;
4. UI lag / WER 1000/1002 incidence is lower in B than A over repeated A-B-A-B runs.
