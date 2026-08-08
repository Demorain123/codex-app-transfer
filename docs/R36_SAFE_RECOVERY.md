# r36 Safe Recovery

r36 adds an explicit **Try recovery** action to the chain-health center. It is deliberately conservative: recovery is allowed to repair the local Transfer listener and, only when there is concrete local failure evidence, restart the specific Docker container that owns the active gateway port.

## Recovery classification

- `transfer_stopped`: start/rebuild the Transfer listener on the configured port.
- `gateway_unreachable` / `docker_target_failed`: if the target container is stopped, restarting, unhealthy, or the active port is refusing/timing out, restart that one container and refresh Transfer.
- `upstream_rate_limited`: do not restart healthy infrastructure and do not generate extra model requests; wait for account/upstream cooldown.
- `upstream_backend_failure`: refresh Transfer's resolver/listener, but deliberately do **not** restart a healthy Sub2API container. A raw 502/503/504 with healthy local gateway is treated as scheduler/account-pool/final-upstream evidence.

## Safety boundaries

Recovery is user-triggered and has a 45-second in-process cooldown. It never runs `docker compose down`, deletes/recreates containers, modifies volumes/databases/accounts, pulls or changes images, reads container environment variables, or sends an inference request. The UI reports every action as performed, skipped, or failed and states when the next real Codex request is required to verify recovery.
