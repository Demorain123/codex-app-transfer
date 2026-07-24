# Subagent retry diagnostics (r16)

This diagnostic is for one question only:

> Does a spawned Codex subagent inherit the parent's provider-level `stream_max_retries`, or does the child session fall back to Codex's default of 5?

It deliberately separates two independent observations:

- **A — Effective config lock export:** inspect the effective session config that Codex resolved for parent and child threads.
- **B — One-shot synthetic 429:** deterministically force exactly one eligible Grok subagent request to reconnect so the UI reveals `Reconnecting 1/N` without waiting for a natural upstream rate limit.

## Safety / scope

The r16 fault injector is disabled by default. It can only trigger when all of these are true:

1. the provider is an explicit Responses provider with `sub2apiGrokCompat=true`;
2. the model is `grok-*`;
3. Codex marks the request as a subagent with `x-openai-subagent` or `x-codex-parent-thread-id`;
4. the local arming flag exists at `~/.codex-app-transfer/subagent-retry-diag.flag`;
5. this Transfer process has not injected once already.

The flag is deleted immediately after the synthetic 429 is consumed. GPT/OpenAI models and main-agent requests are not eligible. No prompt, tool arguments, API keys, header values, or request bodies are logged.

## A. Export effective Codex session configs

Codex exposes a debug config-lock exporter. For the test, add this temporary block to `~/.codex/config.toml`:

```toml
[debug.config_lockfile]
export_dir = "C:/Users/Demorain/.codex-app-transfer/subagent-retry-diag/config-locks"
save_fields_resolved_from_model_catalog = true
```

Create the directory if desired (Codex may create it itself):

```powershell
New-Item -ItemType Directory -Force "$HOME\.codex-app-transfer\subagent-retry-diag\config-locks" | Out-Null
```

Restart Codex Desktop after changing `config.toml`, then:

1. create/use a parent session that is known to show `Reconnecting x/15` when it reconnects;
2. spawn one `grok-4.5` / `high` subagent with `fork_context=false`;
3. wait until the child has started and issued at least one model request;
4. inspect the newest files under the export directory.

The fields of interest are:

```text
model_provider
stream_max_retries
request_max_retries
stream_idle_timeout_ms
model
```

PowerShell quick search:

```powershell
Get-ChildItem "$HOME\.codex-app-transfer\subagent-retry-diag\config-locks" -File -Recurse |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 20 |
  ForEach-Object {
    "`n===== $($_.FullName) ====="
    Select-String -Path $_.FullName -Pattern 'model_provider|stream_max_retries|request_max_retries|stream_idle_timeout_ms|grok-4.5|gpt-5.6-luna'
  }
```

Do not use a lock file as `load_path`; this test is export-only.

## B. Deterministically force one Grok subagent reconnect

With r16 running, arm exactly one synthetic 429:

```powershell
New-Item -ItemType File -Force "$HOME\.codex-app-transfer\subagent-retry-diag.flag" | Out-Null
```

Then spawn one Grok 4.5 High child and give it a harmless read-only task that causes a normal model request. The first eligible child request receives:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 1
Content-Type: application/json
```

with a diagnostic error code `subagent_retry_diag`.

Observe the Codex child UI:

```text
Reconnecting 1/15  -> child inherited the configured retry budget
Reconnecting 1/5   -> child resolved/fell back to the default retry budget
```

The flag is consumed automatically. To repeat the test, create it again. To disarm before it fires:

```powershell
Remove-Item "$HOME\.codex-app-transfer\subagent-retry-diag.flag" -ErrorAction SilentlyContinue
```

Transfer logs contain only compact diagnostics such as:

```text
[subagent-retry-diag] injecting synthetic one-shot HTTP 429; model=grok-4.5 subagent_header=true parent_thread_header=true
[subagent-retry-diag] armed flag consumed; this process will not inject again
```

## Interpreting A + B together

| Effective child config | Forced reconnect | Interpretation |
|---|---|---|
| `stream_max_retries = 15` | `1/15` | inheritance works; no bug reproduced |
| missing / 5 | `1/5` | child effective provider config lost retry tuning |
| `stream_max_retries = 15` | `1/5` | retry budget is being replaced later than config resolution; inspect child `ModelClient` / transport construction |
| missing / 5 | `1/15` | UI/request path differs from exported lock; investigate which config snapshot the child transport actually uses |

After the test, remove the temporary `[debug.config_lockfile]` block if you do not want Codex to keep exporting config locks.
