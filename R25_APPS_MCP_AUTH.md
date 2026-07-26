# r25 — Generic ChatGPT Apps MCP Auth Compatibility

r25 addresses one narrowly-scoped relay failure: Codex Desktop may send requests to the ChatGPT-hosted Apps MCP namespace through Transfer without an `Authorization` header even though the currently-active `~/.codex/auth.json` is a valid real ChatGPT login.

## Scope

Only these relay paths are eligible:

- `/backend-api/ps/mcp`
- `/backend-api/ps/mcp/*`

All other ChatGPT backend paths, normal `/responses`, Sub2API/Grok traffic, and third-party provider requests are outside the r25 injection path.

## Rehydration rules

r25 may add the minimum identity only when all gates pass:

1. the request is already in the hard-coded `https://chatgpt.com` backend passthrough path;
2. the path matches the exact Apps MCP allowlist above;
3. Codex did not provide `Authorization` itself;
4. synthetic account mode is off;
5. the currently-active `~/.codex/auth.json` is `auth_mode=chatgpt`, has non-empty ChatGPT access/refresh tokens, and its access token is not locally expired.

When eligible, r25 adds:

- `Authorization: Bearer <current access token>`;
- `ChatGPT-Account-ID: <current account id>` only when an account id exists and Codex did not already provide that header.

Imported/pinned mirror credentials are deliberately excluded. r25 never refreshes tokens and never reads provider/Sub2API credentials for this feature.

## Privacy / failure behaviour

- token/account values are never written to normal `[apps-mcp-auth]` telemetry;
- malformed credential header values fail closed and the request continues without synthesized auth;
- 401 revocation correlation fingerprints the actually prepared outbound request, so an injected bearer is correlated correctly;
- existing inbound Authorization and account identity are preserved;
- the existing proxy-only/router API remains available without desktop-auth dependencies.

## Evidence boundary

The historical reproduction shows repeated HTTP 451 responses on `/backend-api/ps/mcp*` while other ChatGPT backend endpoints returned 200. r25 tests the specific hypothesis that missing official ChatGPT identity on the hosted Apps MCP relay is the cause. A green build proves the implementation is scoped and compiles; it does **not** prove the upstream 451 root cause. Real-device acceptance requires observing the r25 rehydration marker followed by the upstream MCP result.
