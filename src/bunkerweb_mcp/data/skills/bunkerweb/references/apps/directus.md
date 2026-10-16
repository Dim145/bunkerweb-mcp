# Directus behind BunkerWeb

Template: https://github.com/bunkerity/bunkerweb-templates/tree/main/templates/directus (read at hub commit 4ba433a, 2026-09-19). The template says it was validated on Directus 11 and BunkerWeb 1.6.14. Applied unchanged to Directus 12.4.1 on BunkerWeb 1.6.15 it passed every flow in block mode, so this stack needed no extra exclusion.

## What Directus needs from BunkerWeb

- **WebSocket.** `REVERSE_PROXY_WS=yes`, with buffering off (`REVERSE_PROXY_BUFFERING=no`, `REVERSE_PROXY_REQUEST_BUFFERING=no`) and long timeouts (`3600s` read and send). The template sets all of these. Directus must also have `WEBSOCKETS_ENABLED=true`.
- **Methods.** `ALLOWED_METHODS=GET|POST|HEAD|PUT|DELETE|PATCH|OPTIONS`. This value drops the default `QUERY`; no flow here used it, and `|QUERY` at the end keeps it. The BunkerWeb default at v1.6.15 is `GET|POST|HEAD|QUERY`, which would answer `405` to `PATCH` and `DELETE`.
- **Sizes.** `MAX_CLIENT_SIZE=1024m`, and `MODSECURITY_REQ_BODY_NO_FILES_LIMIT=10485760` (10 MiB of non-file body; the 2 MB JSON import passed with it). Directus has its own JSON limit, `MAX_PAYLOAD_SIZE` (default 1 MB): a 2 MB array answered `Invalid payload. request entity too large.` until it was set to `10mb`.
- **The `Expect` header.** CRS 4 lists `expect` among the restricted headers (rule 920450). curl and many HTTP libraries send `Expect: 100-continue` above 1 KB, so bulk writes got `403`. The template's `modsec-crs` config `directus-crs-tuning` resets `tx.restricted_headers_basic` without `/expect/`. Without that config the same 2 MB request got `403` with rule 920450 in the log. The config is global and keeps every other restricted header.
- **Rate and bad behavior.** `LIMIT_REQ_RATE=25r/s` and `BAD_BEHAVIOR_STATUS_CODES=400 405 444` (no `401`, `403`, `404`) kept the admin app and the API free of `429` and bans. Eight parallel connections loading the admin assets three times all got `200`.
- **CORS and CSP.** `USE_CORS=yes` with `CORS_ALLOW_ORIGIN=self` answered the same-origin preflight with `204`. The template keeps Directus's own CSP headers (`KEEP_UPSTREAM_HEADERS`) and runs BunkerWeb's in report-only mode.

## Verified live

Directus 12.4.1, PostgreSQL 17.11, BunkerWeb 1.6.15 (Docker), CRS 4.29.0, 2026-10-06. Template settings and its one config, no changes.

| Flow                                                                                                    | Detect | Block |
| ------------------------------------------------------------------------------------------------------- | ------ | ----- |
| Ping, admin app, login, `GET /users/me`, `GET /server/info`                                             | pass   | pass  |
| Create collection, create item with HTML body, three query styles (JSON filter, bracket filter, search) | pass   | pass  |
| `PATCH` and `DELETE` item                                                                               | pass   | pass  |
| 21 MB upload (multipart `POST /files`), 21 MB download and a ranged request (`206`)                     | pass   | pass  |
| 2 MB JSON array with `Expect: 100-continue`                                                             | pass   | pass  |
| GraphQL, `/graphql/system`                                                                              | pass   | pass  |
| WebSocket: `101`, auth, subscribe, create event received                                                | pass   | pass  |
| CORS preflight, token refresh, logout                                                                   | pass   | pass  |

No ModSecurity rule fired in either mode. Boundary checks of the template's config, all `403` with rule 920450 and `949110` in the log: `X-HTTP-Method-Override`, `Proxy`, `Content-Encoding` and `X-Middleware-Subrequest` headers on `/items/articles`, and `X-HTTP-Method-Override` on `/graphql`. A SQL injection string in a query or a JSON body, an XSS string, a path traversal and a `sqlmap/1.7` agent all got `403`.

## Not tested

Directus Flows and extensions, SSO login, the `/extensions` and `/metrics` routes, Redis-backed rate limits, S3 storage, and Let's Encrypt.
