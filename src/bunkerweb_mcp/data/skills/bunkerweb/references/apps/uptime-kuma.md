# Uptime Kuma behind BunkerWeb

No template-hub entry exists for Uptime Kuma. Every setting below was tested live on BunkerWeb 1.6.15; see [Verified live](#verified-live).

- **Upstream.** Proxy to `http://<kuma>:3001`. The whole UI runs over Socket.IO, so a missing WebSocket rule breaks the app, not one feature.
- **WebSockets.** `REVERSE_PROXY_WS` defaults to `no`, and the upgrade on `/socket.io/` then got `400`. Scope it with a second rule: `REVERSE_PROXY_URL_1=/socket.io/`, the same `REVERSE_PROXY_HOST_1`, `REVERSE_PROXY_WS_1=yes`.
- **Polling fallback.** The client starts with HTTP long polling and posts its packets as `text/plain`, which CRS rule 920420 ("content type is not allowed") refuses: a warning in detect, `403` in block. Exclude it for that request shape only, in a `modsec-crs` config (920420 runs in phase 1): a chained rule on `^/socket.io/$`, method `POST`, header `Content-Type` matching `^text/plain`, action `ctl:ruleRemoveById=920420`. `ctl:ruleRemoveTargetById=920420;TX:content_type` loaded but did nothing. Write it as in [bunkerweb-modsecurity-crs-tuning](../../../bunkerweb-modsecurity-crs-tuning/SKILL.md). A `text/plain` body on that path is then not inspected at all (the CRS has no parser for it).
- **Rate limit.** One page load makes a polling `GET`, a `POST`, another `GET` and the WebSocket upgrade within a second. At the default `LIMIT_REQ_RATE=2r/s` the connect failed in block mode with `429`. `50r/s` passed. Rate-limit decisions are logged in detect mode as `[ACCESS] detected deny access from limit`.
- **Error bodies.** Set `REVERSE_PROXY_INTERCEPT_ERRORS=no`. The push endpoint answers an unknown token with `404` and `{"ok":false,...}`, which BunkerWeb replaces with its HTML page under the default.
- **Methods.** Nothing to change: the REST side (`/api/push/<token>`, `/api/status-page/<slug>`, `/metrics`) only uses `GET`.
- **Uploads.** There is no HTTP upload. A status-page logo travels as base64 inside a socket message: 0.5 MiB saved, and 5 MiB made Uptime Kuma close the socket with code 1009. No body-size setting of BunkerWeb applies after the upgrade, and ModSecurity logged nothing for the HTML and CSS of the saved status page.
- **First run.** Uptime Kuma 2 starts a database wizard. `GET /` redirects to `/setup-database`, `POST /setup-database` with `{"dbConfig":{"type":"sqlite"}}` answered `{"ok":true}` through BunkerWeb, and the app came up on its own.

## Verified live

Uptime Kuma 2.5.5 (`louislam/uptime-kuma`, SQLite), BunkerWeb 1.6.15, 2026-10-06. Self-signed certificate (`GENERATE_SELF_SIGNED_SSL=yes`), `SERVER_NAME=uptime-kuma.example.com`.

| Flow                                                                       | Detect              | Block                                          |
| -------------------------------------------------------------------------- | ------------------- | ---------------------------------------------- |
| Database wizard, admin setup, login (socket events)                        | pass                | pass                                           |
| Polling handshake and `text/plain` POST                                    | pass, 920420 logged | `403` until the exclusion, then pass           |
| WebSocket upgrade on `/socket.io/`                                         | `400`               | `101` after the `/socket.io/` rule             |
| HTTP and push monitors, API key, `/metrics` with Basic auth, push endpoint | pass                | pass                                           |
| Push with an unknown token returns JSON                                    | HTML                | JSON after `REVERSE_PROXY_INTERCEPT_ERRORS=no` |
| Status page saved with HTML, CSS and markdown; public page and REST read   | pass                | pass                                           |
| Page-load burst of static files                                            | pass                | pass at `50r/s`; the connect failed at `2r/s`  |

Boundary checks: the exclusion was tried with another content type on the same path, with `text/plain` on another path, on a path with an extra segment, with a form body carrying SQLi on the same path, and with `PUT`. All were refused (`403`, or `405` for `PUT`). A POST to `/socket.io` without the slash gets nginx's `301` to the excluded path.

Not tested: notification providers, Docker and database monitors, status-page domain mapping, MariaDB mode, and a real browser (all flows were scripted).
