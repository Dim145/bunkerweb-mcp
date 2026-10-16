# Keycloak behind BunkerWeb

No template-hub entry exists for Keycloak. Every setting below was tested live on BunkerWeb 1.6.15; see [Verified live](#verified-live).

- **Upstream.** Proxy to `http://<keycloak>:8080` and run Keycloak with `KC_HTTP_ENABLED=true`, `KC_PROXY_HEADERS=xforwarded` and `KC_HOSTNAME=<the public https URL>`. With a fixed hostname the issuer in tokens and discovery matched the public URL, port included.
- **Error bodies.** Set `REVERSE_PROXY_INTERCEPT_ERRORS=no`. With the default `yes` BunkerWeb replaces the OAuth error reply (`{"error":"invalid_grant"}`) with its own HTML page.
- **Methods.** The admin REST API saves with `PUT` and deletes with `DELETE`. Set `ALLOWED_METHODS=GET|POST|HEAD|OPTIONS|PUT|PATCH|DELETE`. This value drops the default `QUERY`; no flow here used it, and `|QUERY` at the end keeps it. Without it each call answers `405`; in detect mode the same `PUT` and `DELETE` calls also scored 5 in ModSecurity (rule 949110).
- **Rate limit.** The default `LIMIT_REQ_RATE=2r/s` limited the token endpoint and the admin console's static files in block mode (24 of 30 asset requests got `429`). `100r/s` passed; `50r/s` let one of 30 through as `429`.
- **Big admin bodies.** Importing a 20.6 MiB realm fragment through `POST /admin/realms/<realm>/partialImport` passed after three changes. `MODSECURITY_REQ_BODY_NO_FILES_LIMIT=32m` (default `128k`; ModSecurity rejects larger JSON with `413`, rule 200002) is service-wide, so it raises the buffered JSON size for every path. `REVERSE_PROXY_URL_1=/admin/` with the same host and `REVERSE_PROXY_MAX_CLIENT_SIZE_1=64m` lifts nginx's `10m` for the admin API only. Keycloak answered a 21 MiB upload with an empty `413` of its own (Quarkus default, 10 MB) until `QUARKUS_HTTP_LIMITS_MAX_BODY_SIZE=64M` was set on its container.
- **Bad behavior.** Keycloak's own `400`, `401`, `403` and `404` answers count toward `BAD_BEHAVIOR_THRESHOLD`. A client retrying a wrong password ten times in a minute is banned for 24 h.
- **CRS exclusions** (`modsec` config type, service scope): one chained rule per endpoint, anchored path, methods `POST|PUT`, one target each. Write them as in [bunkerweb-modsecurity-crs-tuning](../../../bunkerweb-modsecurity-crs-tuning/SKILL.md).
  - `/admin/realms/<realm>`, target `ARGS:json.passwordPolicy`, rule 942100. A `regexPattern(...)` password policy reads as SQL injection.
  - `/admin/realms/<realm>/clients/<uuid>/protocol-mappers/models[/<uuid>]` and the same under `client-scopes`, target `ARGS_NAMES:json.config.jsonType.label`, rule 930120. Every OIDC mapper has that key, and the CRS reads `config.json` in its name as an OS file access.
  - Not excluded: a client posted with embedded `protocolMappers` still gets `403`, because the key name contains an array index. Create the client, then add mappers. Regex targets in `ctl:ruleRemoveTargetById` do not help at 1.6.15: with `\`, `^` or `$` the rule failed to load (`Expecting an action`), and a plain `/json.x.array_.*.y/` loaded but never matched (tested on Grafana), so only literal names work.
- **Keycloak side.** Introspection answers `active: false` until the calling client is in the token's audience; add an audience mapper. This is not the proxy.

## Verified live

Keycloak 26.8.0 (`quay.io/keycloak/keycloak`, `start`), PostgreSQL 16.15, BunkerWeb 1.6.15, 2026-10-06. Self-signed certificate (`GENERATE_SELF_SIGNED_SSL=yes`), `SERVER_NAME=keycloak.example.com`.

| Flow                                                                                                                           | Detect                      | Block                                                                                              |
| ------------------------------------------------------------------------------------------------------------------------------ | --------------------------- | -------------------------------------------------------------------------------------------------- |
| Admin token (password grant), realm, user, client, `PUT` and `DELETE`                                                          | pass (methods not enforced) | `405` until `ALLOWED_METHODS`, then pass                                                           |
| Realm password policy with a regex, OIDC mappers                                                                               | pass, CRS hits logged       | `403` until the exclusions, then pass                                                              |
| OIDC: discovery, JWKS, password grant, client credentials, login form to code, token, userinfo, refresh, introspection, logout | pass                        | pass (introspection needs the audience mapper)                                                     |
| OAuth error reply is JSON                                                                                                      | HTML                        | JSON after `REVERSE_PROXY_INTERCEPT_ERRORS=no`                                                     |
| 21 MiB keystore upload, 20.6 MiB `partialImport`                                                                               | `413`                       | `413` until the body settings, then pass (the keystore is random bytes, so Keycloak answers `400`) |
| Admin console static burst (30 requests)                                                                                       | pass                        | `429` at `2r/s`, pass at `100r/s`                                                                  |

Boundary checks: each exclusion was tried with the payload on another target of the same path, on the same target of another path, on a near path (trailing slash) and with `PATCH`. All returned `403` with rule `949110`.

Detect mode logs rate-limit decisions as `[ACCESS] detected deny access from limit` but writes nothing for the method check, so `405` first shows up after the switch to block.

Not tested: WebSockets (Keycloak has none), SAML logins, LDAP and identity-provider brokering, the account console, a real browser (all flows were scripted), and clusters.
