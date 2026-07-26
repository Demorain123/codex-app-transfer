# r25 — Generic ChatGPT Apps MCP Auth Compatibility

r25 addresses one narrowly-scoped relay failure: Codex Desktop may send requests to the ChatGPT-hosted Apps MCP namespace through Transfer without an `Authorization` header even though the currently-active `~/.codex/auth.json` is a valid real ChatGPT login.

## Scope

Only these relay paths are eligible:

- `/backend-api/ps/mcp`
- `/backend-api/ps/mcp/*`

The allowlist is checked after URL canonicalization, so dot-segment forms such as `mcp/../plugins` and percent-encoded equivalents cannot escape the MCP namespace while still receiving synthesized identity.

All other ChatGPT backend paths, normal `/responses`, Sub2API/Grok traffic, and third-party provider requests are outside the r25 injection path.

## Rehydration rules

r25 may add the minimum identity only when all gates pass:

1. the request is already in the hard-coded `https://chatgpt.com` backend passthrough path;
2. the canonical path matches the exact Apps MCP allowlist above;
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
- both synthesized identity header values are marked sensitive;
- an Apps MCP redirect is allowed to retain synthesized identity only on the original `https://chatgpt.com` origin; a cross-host, cross-scheme, or cross-port redirect is blocked before the custom `ChatGPT-Account-ID` can follow it;
- the redirect restriction is scoped only to chains originating from the hosted Apps MCP namespace, so unrelated providers keep the existing redirect behaviour;
- 401 revocation correlation fingerprints the actually prepared outbound request, so an injected bearer is correlated correctly;
- existing inbound Authorization and account identity are preserved;
- the existing proxy-only/router API remains available without desktop-auth dependencies.

## Deep self-review findings

The implementation was deliberately reviewed beyond compilation. Three concrete issues were found and corrected before acceptance:

1. header construction originally used a less robust parsing path; r25 now uses byte-validated header construction and fails closed on malformed values;
2. a raw prefix-only path check could authorize a dot-segment escape after URL normalization; the injection allowlist now evaluates the canonical outbound URL and has negative regressions for literal and percent-encoded `..`;
3. reqwest strips `Authorization` on cross-origin redirects but does not know that `ChatGPT-Account-ID` is also identity-sensitive; r25 now adds an Apps-MCP-only same-origin redirect guard and marks both synthesized values sensitive.

The replayable revision stack contains separate base, redirect-hardening, semantic-review, and redirect-review scripts so these security properties are checked again after future upstream rebases.

## Evidence boundary

The historical reproduction shows repeated HTTP 451 responses on `/backend-api/ps/mcp*` while other ChatGPT backend endpoints returned 200. r25 tests the specific hypothesis that missing official ChatGPT identity on the hosted Apps MCP relay is the cause. A green build proves the implementation is scoped and compiles; it does **not** prove the upstream 451 root cause. Real-device acceptance requires observing the r25 rehydration marker followed by the upstream MCP result.
