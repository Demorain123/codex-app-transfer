# r34 Runtime Behavior Health

r34 extends the r33 read-only Chain Health center with runtime behavior evidence.

## New diagnostics

- Session / Turn request lifecycle: accepted, forwarded, response headers, first converted event, terminal completion/failure/cancellation.
- Best-effort detection of header stalls, first-event stalls, incomplete streams, and a later successful retry after a silent/failed request.
- MCP health scoped to candidate helper processes that are descendants of the current Codex Desktop/app-server generation.
- Recent MCP Exit Guard cleanup/inventory failures from its local JSONL event stream.
- Docker restart deltas. Historical cumulative `RestartCount` is informational and no longer permanently degrades a healthy stack.

## Privacy boundary

Automatic diagnostics do not read or store prompt/response bodies, SSH commands, tool arguments, credentials, raw thread/session/request identifiers, process command lines, container environment variables, mounts, healthcheck output, or container logs.

Conversation correlation is an eight-character non-reversible local fingerprint. MCP process inspection uses executable names and parent topology only. The first release is read-only and never restarts services or kills processes.
