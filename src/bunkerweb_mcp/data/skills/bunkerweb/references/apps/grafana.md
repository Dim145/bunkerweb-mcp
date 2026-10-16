# Grafana behind BunkerWeb

No template-hub entry exists for Grafana. Every setting below was tested live on BunkerWeb 1.6.15; see [Verified live](#verified-live).

- **Upstream.** Proxy to `http://<grafana>:3000`. Set `GF_SERVER_ROOT_URL` to the public URL, port included.
- **Login page in block mode.** The HTML pages embed plugin names such as `SQLConnect`. The CRS response rule 953100 ("PHP Information Leakage") reads that as a leak, and in block mode its outbound score (959100, phase 4) cuts the page after about 40 KB: the client sees `200` and a truncated body. Remove the rule for HTML page loads only, with a chained rule in a `modsec` config: `GET` plus an `Accept` header containing `text/html`, `ctl:ruleRemoveById=953100`. The same page requested with `Accept: application/json` was still cut.
- **Error bodies.** Set `REVERSE_PROXY_INTERCEPT_ERRORS=no`. With the default `yes` the JSON `401` of the API and the SQL error replies of `/api/ds/query` reach clients as BunkerWeb's HTML page.
- **Methods.** Grafana saves with `PUT` and `PATCH` and deletes with `DELETE`. Set `ALLOWED_METHODS=GET|POST|HEAD|OPTIONS|PUT|PATCH|DELETE`. This value drops the default `QUERY`; no flow here used it, and `|QUERY` at the end keeps it.
- **WebSockets.** Grafana Live (`/api/live/ws`) needs `REVERSE_PROXY_WS=yes` (default `no`; without it the upgrade got `400`). Scope it: `REVERSE_PROXY_URL_1=/api/live/`, the same `REVERSE_PROXY_HOST_1`, `REVERSE_PROXY_WS_1=yes`.
- **Rate limit.** The default `LIMIT_REQ_RATE=2r/s` limited the data-source queries and the page's static files in block mode (10 of 30 asset requests got `429`). `100r/s` passed.
- **Body size.** `MODSECURITY_REQ_BODY_NO_FILES_LIMIT` defaults to `128k`: ModSecurity rejects larger JSON with rule 200002, so a 200 KiB dashboard failed to save and a 100 KiB one passed. `32m` passed a 15 MiB dashboard. It is service-wide. nginx's `10m` default also needs lifting for big saves: `REVERSE_PROXY_URL_2=/api/dashboards/`, the same host, `REVERSE_PROXY_MAX_CLIENT_SIZE_2=64m`. Grafana itself refuses dashboards over 16 MB with its own JSON `413`.
- **Bad behavior.** Grafana's own `401`, `400` and `404` answers count toward `BAD_BEHAVIOR_THRESHOLD`; ten in a minute is a 24 h ban for that IP.
- **CRS exclusions** (`modsec` config type, service scope), method `POST`:
  - `/api/ds/query`: raw SQL in `json.queries[n].rawSql` fires 942100, 942151, 942160, 942190, 942280, 942320 and 942350. Remove each rule from the literal targets `ARGS:json.queries.array_0.rawSql` to `array_9`. A regex target such as `ARGS:/json.queries.array_.*.rawSql/` parsed but never matched at 1.6.15, and one with `\`, `^`, `$` or `[]` failed to parse. A query at index 10 still gets `403`.
  - `/api/dashboards/db`: panel and query indices vary, so no literal list works. The narrowest option that passed removes `ruleRemoveById` 932340, 941100, 941120, 941160, 941390, 942100 and 942190 for the whole body of that one endpoint. SQL in the dashboard title is then accepted, and other rules (for example 941110 on a `<script>` title) still fire.
  - Write the rules as in [bunkerweb-modsecurity-crs-tuning](../../../bunkerweb-modsecurity-crs-tuning/SKILL.md).

## Verified live

Grafana 13.2.3 (`grafana/grafana`), PostgreSQL 16.15 as the data source, BunkerWeb 1.6.15, 2026-10-06. Self-signed certificate (`GENERATE_SELF_SIGNED_SSL=yes`), `SERVER_NAME=grafana.example.com`.

| Flow                                                                 | Detect                  | Block                                                                    |
| -------------------------------------------------------------------- | ----------------------- | ------------------------------------------------------------------------ |
| Login page, `/api/health`, login, session and basic-auth API calls   | pass                    | page cut at about 40 KB until the 953100 rule, then pass                 |
| Service account and token, `PUT`, `PATCH`, `DELETE`                  | pass (not logged)       | `405` until `ALLOWED_METHODS`, then pass                                 |
| PostgreSQL data source, queries with `UNION`, `OR`, comments, quotes | pass, CRS hits logged   | pass after the exclusions                                                |
| Dashboard with HTML text panel, SQL and PromQL                       | pass, CRS hits logged   | pass after the exclusions                                                |
| JSON error replies                                                   | HTML                    | JSON after `REVERSE_PROXY_INTERCEPT_ERRORS=no`                           |
| Dashboard JSON of 200 KiB, 1 MiB, 15 MiB                             | `413` at 21 MiB (nginx) | rejected at the `128k` default, then pass; Grafana's own `413` at 21 MiB |
| WebSocket `/api/live/ws`                                             | `400`                   | `101` after the `/api/live/` rule                                        |
| Static burst, 30 requests                                            | pass                    | `429` at `2r/s`, pass at `100r/s`                                        |

Boundary checks: each exclusion was tried on another field of the same path, on the same target of another path, on a near path, with another method, and with a query index beyond the list. B1 to B8 each returned `403` with the rule id logged. Two results are `200` on purpose. B9: SQL in a dashboard title on `/api/dashboards/db` is accepted, because the exclusion above removes those rules for the whole body of that endpoint (the disclosed broad exception; a `<script>` title still got `403`). E3: `GET /login` with `Accept: application/json` returned `200` with a body cut after 40,681 bytes by the response rule `953100`, while the same page with `Accept: text/html` came back complete (59,579 bytes).

Detect mode logs rate-limit decisions as `[ACCESS] detected deny access from limit` but writes nothing for the method check, so `405` first shows up after the switch to block.

Not tested: alerting, Loki and Prometheus data sources, plugin installs, SSO login, a real browser (all flows were scripted), and uploads over 16 MB (Grafana has none).
