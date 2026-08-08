# r35 Real Upstream Health

r35 fixes a diagnostic correctness bug found with Sub2API/Grok retries: the real gateway/provider could return 502/429/503, while the Responses adapter converted that error into a client-facing HTTP 200 `response.failed` stream. r34 then treated the converted 200 as the upstream result.

## Semantics

Each lifecycle now keeps both:

- `raw_upstream_status`: final HTTP status received from the actual gateway/provider after transparent retries.
- `client_status`: HTTP status delivered to Codex after adapter conversion.

The top success/failure counters use the raw result. A client-facing 200 can therefore still be classified as an upstream failure.

The passive upstream card uses structured lifecycle data rather than log ordering and reports the latest raw status, client status, request size, correlated failure streak, failure sequence, and cumulative retry upload bytes.

## MCP attribution

r34 used every `ChatGPT.exe` Electron process as an MCP root, which over-counted renderer/utility descendants. r35 prefers the `codex.exe` app-server generation and only falls back to top-level ChatGPT processes if no app-server root is visible.

## Privacy

Routine upstream error logs no longer include a request-body preview. They retain request byte count, redacted headers, raw HTTP status, and a bounded upstream error-response preview. The health center still stores no prompt, response content, SSH command, tool arguments, credentials, or raw conversation identifiers.
