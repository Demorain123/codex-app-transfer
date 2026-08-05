# r33 Chain Health

r33 adds a privacy-bounded, read-only chain health center to the existing **Route** page.
It preserves the complete validated r32 stack: provider routing, Sub2API Grok compatibility,
Hybrid Direct, Auto Review, runtime diagnostics, No Lagging, MCP Exit Guard, and sortable usage headers.

## Problem statement

A Codex request can appear to be stuck at **Thinking** even though different parts of the path fail:

```text
User action
  -> Codex Desktop UI / app-server
  -> Codex App Transfer listener and adapters
  -> Sub2API / CPA / New API gateway
  -> Docker Desktop / Docker Engine / native process runtime
  -> Redis / PostgreSQL / other Compose dependencies
  -> final OpenAI / third-party / Grok upstream
  -> streaming response back through the same path
```

The Route page previously reported only whether Transfer itself was listening and the cumulative
request counters. A green listener could coexist with a wedged Docker daemon, an unresponsive local
gateway, a stopped Redis/PostgreSQL dependency, or a request that had been forwarded but never
received upstream response headers.

## Design references

The implementation intentionally borrows only narrow ideas from established monitoring tools:

- Prometheus Blackbox Exporter: separate protocol probes (DNS/TCP/HTTP) with strict timeouts;
- Uptime Kuma: distinguish HTTP/TCP endpoint reachability from Docker container state;
- Netdata/Beszel: show container state/health and bounded resource snapshots;
- Docker Engine API/CLI: daemon ping/info, container inspect state, health, restart/OOM evidence,
  one-shot stats, and Compose labels;
- OpenTelemetry HTTP conventions: keep transport and HTTP evidence distinct instead of flattening
  all failures into a generic request error.

r33 does **not** embed these projects, expose the Docker socket, or introduce a monitoring server.
It remains a small local diagnostic layer inside Transfer.

## Automatic checks

The page refreshes every ten seconds. Backend snapshots are cached for eight seconds so opening the
page or multiple UI refreshes do not create a command storm.

### Codex layer

On Windows, a ToolHelp process snapshot counts only `ChatGPT.exe` and `codex.exe`. It does not query
process command lines and does not use WMI. A high `codex.exe` count is shown as degraded evidence,
not used as a reason to terminate anything.

### Transfer layer

Reports the actual listener state/port, active provider, and cumulative request counters.

### Gateway layer

For the active provider only:

1. parse and sanitize the base URL;
2. remove URL userinfo, query, and fragment before returning it to the UI;
3. DNS lookup with a two-second deadline;
4. TCP connect with a two-second deadline;
5. unauthenticated HEAD, falling back to GET only when HEAD transport fails;
6. no redirects and a four-second total HTTP deadline.

The probe stops after response headers. It does not send a model request and does not consume a
response body.

### Runtime layer

For loopback gateways, r33 first checks Docker through bounded CLI calls:

```text
docker desktop status --format json   (optional capability)
docker info --format ...              (daemon responsiveness)
docker ps -aq --filter publish=PORT   (port-to-container discovery)
docker inspect ...                    (state/health/restart/OOM/Compose labels)
docker stats --no-stream ...          (bounded one-shot resource evidence)
```

If `docker info` itself times out, r33 classifies the Docker daemon/Desktop as potentially wedged.
Every child process uses `kill_on_drop` and a hard timeout so a stuck Docker CLI cannot hang Transfer.

When a mapped container has a Compose project label, r33 discovers the project services, ignores
Compose one-off containers, and surfaces the target gateway together with Redis/PostgreSQL or other
service containers. It reads only container state, health, restart count, OOM flag, exit code, labels,
and one-shot statistics. It never reads `Config.Env`, mounted files, secrets, or container logs.

If no Docker container maps the port, Windows falls back to a bounded `netstat` listener lookup and a
ToolHelp PID-to-process-name lookup. Remote gateways skip all local Docker/process checks.

### Upstream layer

Automatic upstream inference would consume quota and could create a new incident. r33 therefore uses
only passive evidence already present in Transfer's privacy-filtered log buffer:

- request forwarded;
- upstream HTTP status received;
- upstream timing/stream completion recorded;
- recent upstream request error.

A request forwarded for 20 seconds without response headers is degraded; at 90 seconds it is treated
as a likely stall. This is explicitly labelled best-effort until a future revision adds per-request
correlation IDs to every lifecycle stage.

## Privacy and safety boundary

Automatic diagnostics:

- do not send inference requests;
- do not read prompt or response text;
- do not read SSH commands or conversation history;
- do not read API keys, OAuth tokens, URL credentials, or container environment variables;
- do not expose or mount the Docker socket;
- do not restart Docker, containers, Codex, or gateway services;
- do not kill processes;
- do not follow HTTP redirects;
- do not run commands without a deadline.

The UI offers only **Check now** and **Details**. Recovery remains a deliberate user action outside the
health endpoint because restarting Docker Desktop affects every container on the machine.

## Status semantics

```text
healthy   = direct evidence is normal
 degraded = reachable but rate-limited/auth-required/starting/historically restarted/waiting
 failed    = explicit timeout, refused connection, 5xx, unhealthy/OOM/restarting container, or stall
 idle      = no Codex process or no real request evidence yet
 unknown   = the platform or configuration does not provide enough evidence
```

## Current limitations

- Passive upstream classification uses ordered log evidence, not a full correlated distributed trace.
- Docker dependency discovery relies on standard Compose labels.
- Native port-owner discovery is currently detailed only on Windows.
- Container `healthy` means only that the image's configured healthcheck passed; it does not prove a
  complete model request through the account pool and final upstream.
- r33 intentionally does not perform an automatic paid/real model request.

## Version

```text
r33 / v2.4.5+33
```
