# Verified live

nginx 1.30.5 (the stable line) and BunkerWeb 1.6.15, 2026-10-06, both in front of the same echo server, one request set sent to each. The source is one `server` block per site with the constructs this skill maps: a `location` with a path in `proxy_pass`, `limit_req` with and without `burst`, `allow`/`deny`, `auth_basic`, `add_header ... always`, `return 301`, `map`, a server-level `proxy_set_header`, `proxy_buffering off`, and a websocket location. The ACL is real-IP based on both sides (`X-Forwarded-For` trusted from private ranges, `USE_REAL_IP=yes`), so the test sends `X-Forwarded-For: 10.1.2.3` (allowed) and `203.0.113.9` (denied). The requests are paced just under one a second; BunkerWeb counts requests per exact URI.

| Request                                                           | nginx                                                                        | BunkerWeb detect  | BunkerWeb block                |
| ----------------------------------------------------------------- | ---------------------------------------------------------------------------- | ----------------- | ------------------------------ |
| `GET /`                                                           | 200                                                                          | 200               | 200                            |
| websocket handshake on `/.ws`, then one echoed text frame         | 101                                                                          | 101               | 403 \*, 101 with the exclusion |
| 4 MiB then 6 MiB multipart upload, server limit `5m`              | 200 / 413                                                                    | 200 / 413         | 200 / 413                      |
| 6 MiB then 21 MiB multipart upload to the `20m` location          | 200 / 413                                                                    | 200 / 413         | 200 / 413                      |
| 4 MiB `application/x-www-form-urlencoded` body                    | 200                                                                          | 200               | 400 \*\*                       |
| 100 B `application/octet-stream` body                             | 200                                                                          | 200               | 403 \*\*\*                     |
| `/admin` allowed address / denied address / `/admin/x`            | 200 / 403 / 403                                                              | 200 / 403 / 403   | 200 / 403 / 403                |
| `/administrator`, denied address (`location /admin` is a prefix)  | 403                                                                          | 403               | 403                            |
| `/private/x` no credentials / right password / wrong password     | 401 / 200 / 401                                                              | 200 / 200 / 200 † | 401 / 200 / 401                |
| `GET /api/users?id=7` (`proxy_pass http://echo:8080/v2/`)         | upstream saw `/v2/users?id=7`                                                | same              | same                           |
| `GET /?tier=gold` (a `map` feeding `proxy_set_header`)            | upstream header `premium`                                                    | same              | same                           |
| user agent `evilbot` (`map` plus server-level `if`, `return 403`) | 403                                                                          | 403               | 403                            |
| `/old`, and `/moved/a/b?x=1` (`return 301 ...$request_uri`)       | 301 to `https://example.org/new`; 301 to `https://example.org/moved/a/b?x=1` | same              | same                           |
| `X-Frame-Options: DENY` and `X-Served-By` on 200 and on 403       | present                                                                      | present           | present                        |
| HSTS header over HTTP / over HTTPS                                | present / present                                                            | absent / present  | absent / present               |
| six `GET /login` with no pause (`3r/m`, `burst=2`)                | 200 x3, then 429 x3                                                          | 200 x6 ‡          | 200 x3, then 429 x3            |
| four `GET /strict` with no pause (`1r/m`, no burst)               | 200, then 429 x3                                                             | 200 x4 ‡          | 200, then 429 x3               |
| `/login` 25 s after the burst, then at 65 s                       | 200, 200                                                                     | not tested        | 429, 200 §                     |
| first body byte, `proxy_buffering off` / default, over HTTPS      | 2 s / 4 s                                                                    | 2 s / 4 s         | 2 s / 4 s                      |
| first body byte, same two, over plain HTTP                        | 2 s / 2 s                                                                    | 2 s / 2 s         | 2 s / 2 s                      |
| unknown `Host`                                                    | connection closed (`return 444`)                                             | 403 ¶             | 403 ¶                          |

The rows that differ:

- \* Block mode needed a scoped exclusion. CRS rule `920440` ("URL file extension is restricted") fires on the path `/.ws`, and `949110` then blocks the handshake. The path belongs to the echo server; `/socket` does not trip it. A service-scoped `modsec-crs` config (scheduler variable `<server_name>_CUSTOM_CONF_MODSEC_CRS_<name>`) holding a `SecRule` on that exact path with `ctl:ruleRemoveById=920440` brought back 101 and the echo. [`bunkerweb-modsecurity-crs-tuning`](https://github.com/bunkerity/bunkerweb-skills/tree/main/skills/bunkerweb-modsecurity-crs-tuning) writes it.
- \*\* ModSecurity rule `200002`: a body that is not a file upload and is larger than `MODSECURITY_REQ_BODY_NO_FILES_LIMIT` (default 131072 bytes) gets 400 in block mode and only a log line in detect. nginx's own `client_max_body_size` is a different limit and let the 4 MiB body through. Setting `MODSECURITY_REQ_BODY_NO_FILES_LIMIT=5242880` on the service gave 200. Multipart uploads are not counted against it.
- \*\*\* CRS rule `920420` rejects content types outside its allowed list, `application/octet-stream` included. The skill above points to the policy variable that widens it.
- † `USE_AUTH_BASIC` is not enforced in detect mode. The challenge header is sent, the request goes through, and the log says `detected deny access from authbasic : missing Authorization header`. Test the credentials again in block mode. BunkerWeb's challenge also carries `charset="UTF-8"`, which nginx's does not.
- ‡ In detect mode a rate limit only logs: `detected client IP ... limit for URL /login (current rate = 4r/m and max rate = 3r/m)`.
- § `limit_req` is a leaky bucket and BunkerWeb's limit is a sliding window with no burst setting. At `3r/m` with `burst=2` both let three requests through and refused the next three. Twenty-five seconds later nginx had earned one request back (200) and BunkerWeb was still limiting (429). At 65 s both answered 200. A BunkerWeb rate of `3r/m` matched `3r/m` with `burst=2` for the first burst; no other pair was tried, so treat any other conversion as a starting point. These last two rows were measured on a separate service with `USE_BAD_BEHAVIOR=no`, see the next section.
- ¶ `DISABLE_DEFAULT_SERVER=yes` answers `DENY_HTTP_STATUS`, `403` by default. `DENY_HTTP_STATUS=444` closes the connection like `return 444` did (checked live on HTTP and HTTPS). It is a global setting for every denial BunkerWeb issues, a ModSecurity block and a ban included, so it cannot be limited to unknown hosts.
- HSTS: `add_header ... always` also answers on plain HTTP; BunkerWeb sends HSTS only over HTTPS (`src/common/core/headers/headers.lua`, the `ssl` check).
- Buffering: with a chunked upstream the difference shows only over HTTPS. `REVERSE_PROXY_BUFFERING=no` gave the first chunk after 2 s and the default after 4 s, which is what nginx did with `proxy_buffering off` and its default. Over plain HTTP both answered at 2 s on both proxies, so a timing test of this setting needs TLS.

## Things the run caught that no row shows

- **Bad-behavior bans.** In block mode BunkerWeb banned the test client for 24 hours (`BAD_BEHAVIOR_BAN_TIME`) once it had collected more than ten answers with status 400, 401, 403, 404, 405, 429 or 444 inside a minute, then answered every request on that service with 403. nginx has nothing like it. `bwcli unban <ip>` in the BunkerWeb container lifts it and `bwcli bans` lists bans. A monitor or script that trips a rate limit can lock itself out the same way. Detect mode counted the answers and did not ban.
- **A server-level `proxy_set_header` is lost.** A `proxy_set_header X-Server-Level yes;` in a `server-http` custom config never reached the upstream: the generated location sets its own headers, so the server-level ones are not inherited. Put each header in `REVERSE_PROXY_HEADERS` of every numbered entry that inherited it in nginx. nginx itself inherits server-level headers only into a location that sets none of its own; the websocket location above set some and lost the server-level `X-Custom-Source`.
- **A path in `REVERSE_PROXY_HOST` replaces the whole URI, query string included.** `http://echo:8080/v2/` as the host sent `GET /v2/users?id=7` upstream as `GET /v2/`. A one-line include on that entry, `rewrite ^/api/(.*)$ /v2/$1 break;`, gave exactly what nginx sent, `GET /v2/users?id=7`.
- **Correction:** that URI rewrite include marked matching requests internal and switched off BunkerWeb's Lua checks for the location. The replacement regex URL and host capture were subsequently run; see "Regex prefix conversion" below.
- **A site with no `proxy_set_header` gets more headers.** nginx sent the upstream `Host: echo:8080` and nothing else. BunkerWeb sent `Host` as the requested name plus `X-Forwarded-For`, `X-Forwarded-Host`, `X-Forwarded-Prefix`, `X-Forwarded-Proto`, `X-Forwarded-Protocol` and `X-Real-IP`. A backend that routes on the `Host` it receives needs `REVERSE_PROXY_HEADERS=Host <name>` on that entry.
- **A raw `add_header` for a managed header doubles it.** `add_header X-Frame-Options DENY always;` in a `server-http` custom config next to the default `X_FRAME_OPTIONS` gave two `X-Frame-Options` lines, `SAMEORIGIN` and `DENY`. `X_FRAME_OPTIONS=DENY` gave one.
- **A `return` location skips the checks.** `location = /ret { return 200 "ok"; }` in a `server-http` custom config answered 200 to `?x=<script>alert(1)</script>` in block mode, while a proxied location answered 403.
- **Custom configs.** `CUSTOM_CONF_HTTP_<name>` on the scheduler (no site prefix) carried the `map` blocks, `<server_name>_CUSTOM_CONF_SERVER_HTTP_<name>` carried the server-level `if`, and a reload accepted both. The `map $http_upgrade $connection_upgrade` block was not copied, since BunkerWeb defines it in its own `http` config; a second copy passed `nginx -t` here, so nginx did not flag the duplicate.
- **`nginx -T`** printed the merged configuration with a `# configuration file <path>:` line before each file it read, `include` files included. `listen 443 ssl http2;` still works on 1.30.5 and prints `the "listen ... http2" directive is deprecated, use the "http2" directive instead`; BunkerWeb needs nothing for it, as `HTTP2` is on by default.

## Not exercised

`error_page`, `gzip`, `proxy_cache`, `auth_request`, `limit_conn`, `geo`, `ssl_ciphers`, `ssl_protocols` on the BunkerWeb side, client certificates, `stream {}` blocks, several `upstream` servers, `proxy_hide_header`, `proxy_next_upstream`, HTTP/2 and HTTP/3 clients. Their rows in `mapping.md` come from the setting definitions at v1.6.15 and were not run.

## Regex prefix conversion

Run on 2026-10-06 with the same source configuration and echo upstream. The regex and host URI expression were copied from the mapping: `^/api/(.*)$` and `http://app:3000/v2/$1$is_args$args`; only the lab upstream name and port changed. Source requests used HTTP; BunkerWeb requests used HTTPS. The comparison below checks status, redirect target and the upstream request line, not TLS or header parity. Requests were paced 1.1 s apart.

Initial mapping:

| Request                | Source upstream line or response                  | BunkerWeb upstream line or response     | Match |
| ---------------------- | ------------------------------------------------- | --------------------------------------- | ----- |
| `/api/x/y?q=1&r=a%20b` | 200: `GET /v2/x/y?q=1&r=a%20b HTTP/1.1`           | 200: `GET /v2/x/y?q=1&r=a%20b HTTP/1.1` | yes   |
| `/api`                 | 301: `http://nginx.example.com/api/`; no upstream | 200: `GET /api HTTP/1.1`                | no    |
| `/api/`                | 200: `GET /v2/ HTTP/1.1`                          | 200: `GET /v2/ HTTP/1.1`                | yes   |
| `/apix`                | 200: `GET /apix HTTP/1.1`                         | 200: `GET /apix HTTP/1.1`               | yes   |
| `/api/a%2Fb`           | 200: `GET /v2/a/b HTTP/1.1`                       | 200: `GET /v2/a/b HTTP/1.1`             | yes   |
| `/api/a%20b`           | 200: `GET /v2/a%20b HTTP/1.1`                     | 200: `GET /v2/a%20b HTTP/1.1`           | yes   |
| `/api/caf%C3%A9`       | 200: `GET /v2/caf%C3%A9 HTTP/1.1`                 | 200: `GET /v2/caf%C3%A9 HTTP/1.1`       | yes   |
| `/api//x`              | 200: `GET /v2/x HTTP/1.1`                         | 200: `GET /v2/x HTTP/1.1`               | yes   |
| `/api/../admin`        | 200: `GET /api/../admin HTTP/1.1`                 | 200: `GET /api/../admin HTTP/1.1`       | yes   |

Separate bare-prefix redirect, both sides over HTTP:

| Request            | Source upstream line or response                              | BunkerWeb upstream line or response                           | Match |
| ------------------ | ------------------------------------------------------------- | ------------------------------------------------------------- | ----- |
| `/api`             | 301: `http://nginx.example.com/api/`; no upstream             | 301: `http://nginx.example.com/api/`; no upstream             | yes   |
| `/api?q=1&r=a%20b` | 301: `http://nginx.example.com/api/?q=1&r=a%20b`; no upstream | 301: `http://nginx.example.com/api/?q=1&r=a%20b`; no upstream | yes   |
| `/apix`            | 200: `GET /apix HTTP/1.1`                                     | 200: `GET /apix HTTP/1.1`                                     | yes   |
| `/api/`            | 200: `GET /v2/ HTTP/1.1`                                      | 200: `GET /v2/ HTTP/1.1`                                      | yes   |

The deep path and query, trailing slash, `/apix`, encoded slash, space, UTF-8 and doubled slash matched. nginx decoded `%2F` to `/` before prefix replacement, and the capture did the same. Bare `/api` was a source `301` to `/api/`, while the initial regex fell through to the unstripped fallback. A separate `REDIRECT_FROM=^/api$`, `REDIRECT_TO=http://nginx.example.com/api/$is_args$args`, `REDIRECT_TO_STATUS_CODE=301` matched the source over HTTP, including `/api?q=1&r=a%20b`; use the served name and intended scheme, and verify HTTPS separately. This fixed target does not establish dynamic scheme or Host parity. `/api/../admin`, sent with `curl --path-as-is`, selected the fallback and preserved its original upstream request line in this prefix-only conversion. Carry any controls on the normalized destination separately. In compose, escape every `$` as `$$`.

### Checks in the regex location

`SECURITY_MODE=block` throughout; `USE_BAD_BEHAVIOR=no`. URI-parity probes initially had `USE_MODSECURITY=no` to separate routing from WAF decisions; then `USE_GREYLIST=yes` with `GREYLIST_IP=198.51.100.1` denied the actual test client. Greylist was disabled before the redirect and XSS run. The self-signed HTTPS service then used `AUTO_REDIRECT_HTTP_TO_HTTPS=yes` and `USE_MODSECURITY=yes`.

- HTTPS `/api/x/y?q=1`: `403`, `[ACCESS] denied access from greylist : not in greylist`.
- HTTP `/api/x/y?q=1`: `301`, `Location: https://nginx.example.com/api/x/y?q=1`; `[ACCESS] ssl redirect ... : redirect to HTTPS`.
- HTTPS `/api/x/y?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E`: `403`, CRS XSS rule `941100` and blocking rule `949110` (the run loaded CRS 4.29.0).
- HTTPS benign control `/api/x/y?q=clean`: `200`, upstream `GET /v2/x/y?q=clean HTTP/1.1`.

Relevant log output (client address redacted; ModSecurity lines reduced to the message, rule and request):

```text
bunkerweb-1     | 2026/10/06 15:05:43 [warn] 302#302: *377 [ACCESS] denied access from greylist : not in greylist, client: <client-ip>, server: nginx.example.com, request: "GET /api/x/y?q=1 HTTP/2.0", host: "nginx.example.com"
bunkerweb-1     | 2026/10/06 15:06:12 [notice] 501#501: *584 [ACCESS] ssl redirect to https://nginx.example.com/api/x/y?q=1 : redirect to HTTPS, client: <client-ip>, server: nginx.example.com, request: "GET /api/x/y?q=1 HTTP/1.1", host: "nginx.example.com"
ModSecurity: XSS Attack Detected via libinjection; rule 941100; request: "GET /api/x/y?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E"
ModSecurity: Access denied with code 403 (phase 2); rule 949110; request: "GET /api/x/y?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E"
```

This proves greylist, the Lua HTTPS redirect and CRS on the tested regex path. It does not establish every Lua plugin or redirect-location security behavior.
