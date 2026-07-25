# Parent/child retry diagnostics (r18)

This diagnostic answers one narrow question:

> Why can a Codex main session use a provider-level `stream_max_retries = 15` while a spawned Grok subagent appears to reconnect only `1/5 ... 5/5`?

It deliberately combines three independent observations:

- **A — Effective config lock export:** inspect the effective session config Codex resolved for parent and child threads.
- **B — Child one-shot synthetic 429:** force exactly one eligible Grok subagent request to reconnect.
- **C — Main one-shot synthetic 429:** force exactly one eligible main-agent request to reconnect in the same Transfer process/provider.

r18 also adds compact request-identity correlation logs so repeated requests can be associated with the same main/child thread without logging raw identity header values.

## Safety / scope

All fault injection is disabled by default.

### Child injector (introduced in r16)

It can trigger only when all are true:

1. the provider is an explicit Responses provider with `sub2apiGrokCompat=true`;
2. the model is `grok-*`;
3. Codex marks the request as a subagent with `x-openai-subagent` or `x-codex-parent-thread-id`;
4. `~/.codex-app-transfer/subagent-retry-diag.flag` exists;
5. this Transfer process has not already injected a child diagnostic fault.

### Main injector (r18)

It can trigger only when all are true:

1. the provider is an explicit Responses provider with `sub2apiGrokCompat=true`;
2. the request contains a model;
3. the request does **not** carry `x-openai-subagent` or `x-codex-parent-thread-id`;
4. `~/.codex-app-transfer/main-retry-diag.flag` exists;
5. this Transfer process has not already injected a main diagnostic fault.

Each flag is deleted immediately after it is consumed. Main and child injectors have independent process guards, so one main fault and one child fault can be tested in the same Transfer process.

No prompt, request body, tool arguments, API keys, authorization values, or raw thread/session/request IDs are logged. Identity values are reduced to short deterministic fingerprints used only to correlate retries.

## A. Export effective Codex session configs

Add this temporary block to `~/.codex/config.toml`:

```toml
[debug.config_lockfile]
export_dir = "C:/Users/Demorain/.codex-app-transfer/subagent-retry-diag/config-locks"
save_fields_resolved_from_model_catalog = true
```

Create/clean the directory before a controlled test:

```powershell
$LockDir = "$HOME\.codex-app-transfer\subagent-retry-diag\config-locks"
Remove-Item "$LockDir\*" -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $LockDir | Out-Null
```

Restart Codex Desktop after changing `config.toml`, then:

1. create a parent Luna session;
2. spawn one `grok-4.5` / `high` / `fork_context=false` worker;
3. wait until both parent and child have issued model requests;
4. inspect the newest lock files.

Fields of interest:

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

Do not use an exported lock as `load_path`; this test is export-only.

## B. Force one Grok child reconnect

Arm one child fault:

```powershell
New-Item -ItemType File -Force "$HOME\.codex-app-transfer\subagent-retry-diag.flag" | Out-Null
```

Then spawn one Grok 4.5 High child and give it a harmless read-only task that causes a normal model request. The first eligible child request receives:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 1
Content-Type: application/json
```

with diagnostic code `subagent_retry_diag`.

Observe the child UI:

```text
Reconnecting 1/15  -> child transport is using the configured retry budget
Reconnecting 1/5   -> child transport is using the default/fallback budget
```

## C. Force one main-agent reconnect

Keep the same Transfer process and provider. Arm the main control:

```powershell
New-Item -ItemType File -Force "$HOME\.codex-app-transfer\main-retry-diag.flag" | Out-Null
```

Immediately send one simple prompt from the Luna main session. The first eligible **non-subagent** request receives one local 429 with `Retry-After: 1` and diagnostic code `main_retry_diag`.

Observe the main UI:

```text
Reconnecting 1/15  -> main transport is using the configured retry budget
Reconnecting 1/5   -> main transport is also using the default/fallback budget
```

The strongest reproduction is:

```text
same Codex process
same Transfer process
same provider/config.toml
main  -> Reconnecting 1/15
child -> Reconnecting 1/5
```

That removes Sub2API timing and natural rate limiting as variables and isolates parent-vs-child runtime configuration.

## Correlation logs

For explicit Sub2API Grok-compat Responses traffic r18 writes one compact line before either injector can return early:

```text
[retry-runtime-diag] target=main model=gpt-5.6-luna provider=sub2api thread=91b62b6f parent=- session=2ee6f355 client_request=dc0a09ad subagent_header=false parent_thread_header=false
[retry-runtime-diag] target=subagent model=grok-4.5 provider=sub2api thread=abc412ef parent=91b62b6f session=6d68a3be client_request=71e21450 subagent_header=true parent_thread_header=true
```

The hexadecimal identity tokens are fingerprints, not raw IDs. Equal fingerprints across retry attempts indicate the same underlying identity value.

Synthetic faults also produce:

```text
[main-retry-diag] injecting synthetic one-shot HTTP 429; model=gpt-5.6-luna ...
[subagent-retry-diag] injecting synthetic one-shot HTTP 429; model=grok-4.5 ...
```

## Disarm / repeat

Disarm flags before they fire:

```powershell
Remove-Item "$HOME\.codex-app-transfer\main-retry-diag.flag" -ErrorAction SilentlyContinue
Remove-Item "$HOME\.codex-app-transfer\subagent-retry-diag.flag" -ErrorAction SilentlyContinue
```

Because each target also has a process-local one-shot guard, **restart Codex App Transfer before repeating the same target's synthetic fault a second time**. Creating the same flag again without restarting Transfer intentionally will not inject a second fault. Main and child guards are independent, so one main + one child test does not require a restart between them.

## Interpretation

| Effective child config | Main forced reconnect | Child forced reconnect | Interpretation |
|---|---:|---:|---|
| 15 | `1/15` | `1/15` | inheritance works; previous `/5` came from a different path/session |
| missing / 5 | `1/15` | `1/5` | child effective provider config lost retry tuning before transport creation |
| **15** | **`1/15`** | **`1/5`** | strongest evidence that child config looks correct but the child `ModelClient`/transport later uses a default provider snapshot |
| missing / 5 | `1/5` | `1/5` | parent control is not using the expected provider tuning; re-check active provider selection |
| 15 | `1/5` | `1/5` | config-lock export and actual transport retry budget diverge for both sessions |

After the test, remove the temporary `[debug.config_lockfile]` block if you do not want Codex to keep exporting config locks.
