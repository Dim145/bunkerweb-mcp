# Verified live

linuxserver SWAG 2.6.0 and BunkerWeb 1.6.15, 2026-10-06, each in front of the same echo server, one request set. SWAG served with a pre-made self-signed certificate placed at `/config/etc/letsencrypt/live/<URL>/` (`fullchain.pem`, `privkey.pem`, no `chain.pem`): its startup log said `Certificate exists; parameters unchanged; starting nginx` and no certificate request was made. BunkerWeb served the same files through `USE_CUSTOM_SSL`; the certificate it presented had the same SHA-256 fingerprint. Everything below ran through SWAG's real nginx, including `proxy.conf`, `ssl.conf` and its fail2ban. Let's Encrypt issuance itself was not run, so the Let's Encrypt rows of the mapping come from the plugin's settings only.

Three services were converted: `app.example.com` (a customised `app.subdomain.conf`: 5 MiB body limit, HSTS, an `/admin` ACL, a `3r/m` limit on `/login`, `auth_basic` on `/secure`, a redirect, trusted `X-Forwarded-For`), `plain.example.com` (the stock template, `client_max_body_size 0`) and `example.com` (a subfolder conf, `/echo/`). The ACL is real-IP based, so the test sends `X-Forwarded-For: 10.1.2.3` (allowed) and `203.0.113.9` (denied).

| Request (HTTPS, `app.example.com` unless noted)                  | SWAG                                 | BunkerWeb detect                                 | BunkerWeb block                  |
| ---------------------------------------------------------------- | ------------------------------------ | ------------------------------------------------ | -------------------------------- |
| `GET /`; `Server` header; HSTS                                   | 200; `nginx`; the `add_header` value | 200; none; the `STRICT_TRANSPORT_SECURITY` value | same as detect                   |
| websocket handshake on `/.ws`, then one echoed text frame        | 101                                  | 101                                              | 101 \*                           |
| 4 MiB / 6 MiB / 12 MiB multipart upload (limit `5m`)             | 200 / 413 / 413                      | 200 / 413 / 413                                  | 200 / 413 / 413                  |
| the same three on `plain.example.com` (`client_max_body_size 0`) | 200 / 200 / 200                      | 200 / 200 / 200 (`MAX_CLIENT_SIZE=0`)            | 200 / 200 / 200                  |
| 4 MiB `application/x-www-form-urlencoded` body                   | 200                                  | 200                                              | 200 \*\*                         |
| 100 B `application/octet-stream` body                            | 200                                  | 200                                              | 403 \*\*\*                       |
| `/admin` allowed address / denied address / `/admin/x`           | 200 / 403 / 403                      | 200 / 403 / 403                                  | 200 / 403 / 403                  |
| `/administrator`, denied address                                 | 200                                  | 200                                              | 200                              |
| `/old`                                                           | 301 to `https://example.org/new`     | same                                             | same                             |
| `/secure`: no credentials / right / wrong password               | 401 / 200 / 401                      | 200 / 200 / 200 \*\*\*\*                         | 401 / 200 / 401                  |
| six `GET /login`, no pause                                       | 200 x3, then 429 x3                  | 200 x6                                           | 200 x3, then 429 x3              |
| six `GET /login` on `plain.example.com`                          | 200 x6                               | 200 x6                                           | 200, 200, then 429 x4 \*\*\*\*\* |
| `http://<served name>/x?y=1`                                     | 301 to `https://<name>/x?y=1`        | same                                             | same                             |
| unknown `Host`, `/` and `/echo/foo`                              | 200 (index page) and proxied         | 403 and 403                                      | 403 and 403                      |
| `example.com` `/echo/foo?x=1`, request the upstream saw          | `GET /foo?x=1`                       | `GET /foo?x=1` (with the include)                | same                             |
| `example.com` `/`                                                | 200 (SWAG's index page)              | 404 (no files served)                            | 404                              |

The rows that differ:

- \* The first conversion in block mode got 403 on the handshake: CRS rule `920440` ("URL file extension is restricted") fires on the path `/.ws`, which is this echo server's own path. A service-scoped `modsec-crs` config (scheduler variable `<server_name>_CUSTOM_CONF_MODSEC_CRS_<name>`) with `ctl:ruleRemoveById=920440` on that exact path fixed it.
- \*\* The first conversion got 400 here: rule `200002` ("Request body excluding files is bigger than the maximum expected"), because `MODSECURITY_REQ_BODY_NO_FILES_LIMIT` defaults to 131072 bytes. Setting it to `5242880` on `app.example.com` (and `13107200` on `plain.example.com`) let the body through. In detect the first conversion got 200.
- \*\*\* CRS rule `920420` rejects content types outside its allowed list, `application/octet-stream` included, with the anomaly score rule `949110` doing the blocking. SWAG has no ModSecurity. See [`bunkerweb-modsecurity-crs-tuning`](https://github.com/bunkerity/bunkerweb-skills/tree/main/skills/bunkerweb-modsecurity-crs-tuning).
- \*\*\*\* Basic auth is not enforced in detect mode: the answer is 200 with the `WWW-Authenticate` header. In block mode it is 401. Plain `allow`/`deny` includes are enforced in both.
- \*\*\*\*\* BunkerWeb limits every client to `2r/s` per URL by default and SWAG has no limit, so `plain.example.com` saw 429 after two requests in block mode. In detect mode the log shows `detected client IP ... limit for URL /login (current rate = 3r/s and max rate = 2r/s)`; on `app.example.com` the converted rule logs `(current rate = 4r/m and max rate = 3r/m)`.
- The first conversion of `plain.example.com` left `MAX_CLIENT_SIZE` at its default `10m`: the 12 MiB upload got 413 where SWAG answered 200.
- HSTS: `plain.example.com` sent none in SWAG and `max-age=63072000; includeSubDomains; preload` in BunkerWeb, the plugin default.
- Prefix: with no include the upstream saw `/echo/foo?x=1`; the include `rewrite ^/echo(.*)$ $1 break;` in `REVERSE_PROXY_INCLUDES` restored `/foo?x=1`. `GET /echo` answered 301 to `/echo/` on both.
- **Correction:** that URI rewrite include marked matching requests internal and switched off BunkerWeb's Lua checks for the location. The replacement regex URL and host capture were subsequently run; see "Regex prefix conversion" below.

## Headers the upstream saw

| Header                                                                          | SWAG     | BunkerWeb                                                          |
| ------------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------ |
| `Host`, `X-Forwarded-For`, `X-Real-IP`, `X-Forwarded-Host`, `X-Forwarded-Proto` | sent     | sent, same values                                                  |
| `X-Forwarded-Protocol`                                                          | not sent | sent                                                               |
| `X-Forwarded-Method`, `X-Forwarded-Uri`, `X-Forwarded-Ssl`, `X-Original-URL`    | sent     | absent until `REVERSE_PROXY_HEADERS` lists them (variables worked) |
| `X-Forwarded-Port`                                                              | `443`    | `8443` when written `$server_port`; use the literal `443`          |
| `Connection`                                                                    | `close`  | `close`                                                            |

## fail2ban against bad behavior

SWAG: six `GET /admin` from `X-Forwarded-For: 203.0.113.9` (403, nginx logs `access forbidden by rule`) put the address in the `nginx-deny` jail, with `fail2ban-client status nginx-deny` showing `Currently banned: 1`. Six wrong passwords on `/secure` from `203.0.113.10` banned it in both `nginx-http-auth` and `nginx-unauthorized`. The ban is an iptables chain inside the SWAG container; the result was read from the jail status, not from a refused request. Three `/phpmyadmin/index.php` and three `/wp-login.php` requests got 404 on the default site and `nginx-botsearch` stayed at 0: that site does not trust `X-Forwarded-For`, the log showed the proxy address `<docker-gateway-ip>`, and that is inside `ignoreip`.

BunkerWeb, block mode, `BAD_BEHAVIOR_THRESHOLD=5`, `BAD_BEHAVIOR_COUNT_TIME=600`, `BAD_BEHAVIOR_BAN_TIME=600` on the service: the same six `/admin` requests logged `[BADBEHAVIOR] IP 203.0.113.9 is banned for 600s (5/5) on server app.example.com with scope service`. The next `GET /` from that address got 403 (`is banned with reason bad behavior`) and a different address got 200. Detect mode, same requests: the next `GET /` got 200 and the log had no counter or ban line.

With the default `10`/`60`/`86400` the probe's own bad responses (413, 403, 429) reached `11/10` on `plain.example.com` in one run and banned the test client for 24 h on that service. Counters are per service; a request to an unknown `Host` is counted on the default server `_` with scope global.

## Not exercised

Let's Encrypt issuance and renewal (any DNS plugin), `proxy_redirect` against a backend that redirects, the 240 s timeouts (set and accepted, no long request sent), `ssl.conf` ciphers against old clients, Authelia, Authentik and LDAP includes, `nginx-badbots` against `BLACKLIST_USER_AGENT`, `ignoreip` against `WHITELIST_IP`, `DOCKER_MODS`, PHP, and the `.htpasswd` hash import (not possible).

## Regex prefix conversion

Run on 2026-10-06 with the same source configuration and echo upstream. The regex and host URI expression were copied from the mapping: `^/echo(/.*)$` and `http://echo:8080$1$is_args$args`; only the lab upstream name and port changed. Source and BunkerWeb requests used HTTPS. Requests were paced 1.1 s apart.

Initial mapping:

| Request                 | Source upstream line or response              | BunkerWeb upstream line or response  | Match |
| ----------------------- | --------------------------------------------- | ------------------------------------ | ----- |
| `/echo/x/y?q=1&r=a%20b` | 200: `GET /x/y?q=1&r=a%20b HTTP/1.1`          | 200: `GET /x/y?q=1&r=a%20b HTTP/1.1` | yes   |
| `/echo`                 | 301: `https://example.com/echo/`; no upstream | 200: `GET /echo HTTP/1.1`            | no    |
| `/echo/`                | 200: `GET / HTTP/1.1`                         | 200: `GET / HTTP/1.1`                | yes   |
| `/echox`                | 301: `https://example.com/echo/`; no upstream | 200: `GET /echox HTTP/1.1`           | no    |
| `/echo/a%2Fb`           | 200: `GET /a/b HTTP/1.1`                      | 200: `GET /a/b HTTP/1.1`             | yes   |
| `/echo/a%20b`           | 200: `GET /a%20b HTTP/1.1`                    | 200: `GET /a%20b HTTP/1.1`           | yes   |
| `/echo/caf%C3%A9`       | 200: `GET /caf%C3%A9 HTTP/1.1`                | 200: `GET /caf%C3%A9 HTTP/1.1`       | yes   |
| `/echo//x`              | 200: `GET /x HTTP/1.1`                        | 200: `GET /x HTTP/1.1`               | yes   |
| `/echo/../admin`        | 200: no upstream                              | 200: `GET /echo/../admin HTTP/1.1`   | no    |

After adding the separate `/echo` prefix redirect:

| Request                 | Source upstream line or response              | BunkerWeb upstream line or response           | Match |
| ----------------------- | --------------------------------------------- | --------------------------------------------- | ----- |
| `/echo/x/y?q=1&r=a%20b` | 200: `GET /x/y?q=1&r=a%20b HTTP/1.1`          | 200: `GET /x/y?q=1&r=a%20b HTTP/1.1`          | yes   |
| `/echo`                 | 301: `https://example.com/echo/`; no upstream | 301: `https://example.com/echo/`; no upstream | yes   |
| `/echo/`                | 200: `GET / HTTP/1.1`                         | 200: `GET / HTTP/1.1`                         | yes   |
| `/echox`                | 301: `https://example.com/echo/`; no upstream | 301: `https://example.com/echo/`; no upstream | yes   |
| `/echo/a%2Fb`           | 200: `GET /a/b HTTP/1.1`                      | 200: `GET /a/b HTTP/1.1`                      | yes   |
| `/echo/a%20b`           | 200: `GET /a%20b HTTP/1.1`                    | 200: `GET /a%20b HTTP/1.1`                    | yes   |
| `/echo/caf%C3%A9`       | 200: `GET /caf%C3%A9 HTTP/1.1`                | 200: `GET /caf%C3%A9 HTTP/1.1`                | yes   |
| `/echo//x`              | 200: `GET /x HTTP/1.1`                        | 200: `GET /x HTTP/1.1`                        | yes   |
| `/echo/../admin`        | 200: no upstream                              | 200: `GET /echo/../admin HTTP/1.1`            | no    |

The deep path/query, trailing slash, encoded slash, space, UTF-8 and doubled slash matched. The source fixture had `location /echo { return 301 $scheme://$host/echo/; }` beside its stripping `/echo/` location: both bare `/echo` and lookalike `/echox` redirected, and the redirect dropped the query. The initial regex matched neither. A separate **prefix** `REDIRECT_FROM=/echo`, `REDIRECT_TO=https://example.com/echo/`, `REDIRECT_TO_STATUS_CODE=301` matched both redirects on the tested HTTPS service, including `/echo?q=1&r=a%20b`; `/echo/` and deeper paths still used the regex. Use `^/echo$` only if the actual source has an exact bare-path redirect. Check other lookalikes and the served name/scheme before cutover. A fixed target does not establish dynamic scheme or Host parity. `/echo/../admin`, sent with `curl --path-as-is`, left the stripping location: SWAG served its static index (`200`, no upstream), while the prefix-only BunkerWeb fixture proxied the original request line. Carry the static fallback and its access controls separately. In compose, escape every `$` as `$$`.

### Checks in the regex location

`SECURITY_MODE=block` throughout; `USE_BAD_BEHAVIOR=no`. URI-parity probes initially had `USE_MODSECURITY=no` to separate routing from WAF decisions; then `USE_GREYLIST=yes` with `GREYLIST_IP=198.51.100.1` denied the actual test client. Greylist was disabled before the redirect and XSS run. The self-signed HTTPS service then used `AUTO_REDIRECT_HTTP_TO_HTTPS=yes` and `USE_MODSECURITY=yes`.

- HTTPS `/echo/x/y?q=1`: `403`, `[ACCESS] denied access from greylist : not in greylist`.
- HTTP `/echo/x/y?q=1`: `301`, `Location: https://example.com/echo/x/y?q=1`; `[ACCESS] ssl redirect ... : redirect to HTTPS`.
- HTTPS `/echo/x/y?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E`: `403`, CRS XSS rule `941100` and blocking rule `949110` (the run loaded CRS 4.29.0).
- HTTPS benign control `/echo/x/y?q=clean`: `200`, upstream `GET /x/y?q=clean HTTP/1.1`.

Relevant log output (client address redacted; ModSecurity lines reduced to the message, rule and request):

```text
bunkerweb-1     | 2026/10/06 15:11:46 [warn] 302#302: *344 [ACCESS] denied access from greylist : not in greylist, client: <client-ip>, server: example.com, request: "GET /echo/x/y?q=1 HTTP/2.0", host: "example.com"
bunkerweb-1     | 2026/10/06 15:12:12 [notice] 493#493: *536 [ACCESS] ssl redirect to https://example.com/echo/x/y?q=1 : redirect to HTTPS, client: <client-ip>, server: example.com, request: "GET /echo/x/y?q=1 HTTP/1.1", host: "example.com"
ModSecurity: XSS Attack Detected via libinjection; rule 941100; request: "GET /echo/x/y?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E"
ModSecurity: Access denied with code 403 (phase 2); rule 949110; request: "GET /echo/x/y?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E"
```

This proves greylist, the Lua HTTPS redirect and CRS on the tested regex path. It does not establish every Lua plugin or redirect-location security behavior.
