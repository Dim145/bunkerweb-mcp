# Verified live

Caddy 2.11.7 (stock image, `auto_https off`) and BunkerWeb 1.6.15, 2026-10-06, both in front of the same echo server, one request set. The ACL is real-IP based (`X-Forwarded-For` trusted from private ranges on both sides), so the test sends `X-Forwarded-For: 10.1.2.3` (allowed) and `203.0.113.9` (denied). Requests are 1.1 s apart, because BunkerWeb limits each client IP to `2r/s` by default.

Automatic HTTPS was off for this table: the source answers on plain HTTP and the BunkerWeb columns are the HTTP port. The HTTPS port gave the same results except HSTS and `X-Forwarded-Proto`. What turning automatic HTTPS off hides, and the certificate side, are in the last section.

| Request                                                        | Caddy                                  | BunkerWeb detect               | BunkerWeb block       |
| -------------------------------------------------------------- | -------------------------------------- | ------------------------------ | --------------------- |
| `GET /`                                                        | 200                                    | 200                            | 200                   |
| websocket handshake on `/.ws`, then one echoed text frame      | 101                                    | 101                            | 101 \*                |
| 4 MiB multipart upload / 6 MiB multipart upload                | 200 / 413                              | 200 / 413                      | 200 / 413             |
| 4 MiB `application/x-www-form-urlencoded` body                 | 200                                    | 200                            | 400 \*\*              |
| 100 B `application/octet-stream` body                          | 200                                    | 200                            | 403 \*\*\*            |
| 5.1 MB body with `request_body { max_size 5MB }`               | 413                                    | 413 \*\*\*\*                   | 413                   |
| `/admin` allowed address / denied address / `/admin/x`         | 200 / 403 / 403                        | 200 / 403 / 403                | 200 / 403 / 403       |
| `/administrator`, denied address                               | 200                                    | 200                            | 200                   |
| `/peer` (`remote_ip` ACL), denied address in `X-Forwarded-For` | 200                                    | 403                            | 403 \*\*\*\*\*        |
| `/old` / `/older` (`redir /old ... 301`)                       | 301 to `https://example.org/new` / 200 | same                           | same                  |
| `/api/x/y?q=1` / `/api` (`handle_path /api/*`)                 | upstream sees `/x/y?q=1` / `/api`      | same                           | same                  |
| `/secure/x`: no password / right password / wrong password     | 401 / 200 / 401                        | 200 / 200 / 200 (not enforced) | 401 / 200 / 401       |
| `header X-Frame-Options DENY`, `header X-Served-By caddy`      | present                                | present                        | present               |
| `encode gzip`, `Accept-Encoding: gzip`, 1.5 KB request header  | `gzip`                                 | `gzip`                         | `gzip`                |
| HSTS header on HTTP / on HTTPS                                 | present / not tested                   | absent / present               | absent / present      |
| six `GET /login` with no pause                                 | 200 x6 (stock Caddy has no limiter)    | 200 x6                         | 200, 200, then 429 x4 |
| unknown `Host`                                                 | 200, empty body                        | 403                            | 403                   |

The rows that differ:

- \* The block run needed a scoped exclusion. CRS rule `920440` ("URL file extension is restricted") fires on the path `/.ws`, the echo server's own path, and the handshake got 403. A path like `/socket` does not trip it. The fix that worked is a service-scoped `modsec-crs` config (scheduler variable `<server_name>_CUSTOM_CONF_MODSEC_CRS_<name>`) with `ctl:ruleRemoveById=920440` matched on that exact path. Use [`bunkerweb-modsecurity-crs-tuning`](https://github.com/bunkerity/bunkerweb-skills/tree/main/skills/bunkerweb-modsecurity-crs-tuning) to write it.
- \*\* ModSecurity rule `200002`: non-file bodies above `MODSECURITY_REQ_BODY_NO_FILES_LIMIT` (default 131072 bytes) get 400 in block mode and a log line in detect. File uploads (multipart) are not counted against it.
- \*\*\* CRS rule `920420` rejects content types outside its allowed list, `application/octet-stream` included. Caddy passes anything.
- \*\*\*\* This is the converted value. The first conversion used `MAX_CLIENT_SIZE=5m` and let the 5.1 MB body through with 200: Caddy's `5MB` is 5,000,000 bytes, nginx's `5m` is 5,242,880. `MAX_CLIENT_SIZE=5000000` matches, because the setting accepts a plain byte count.
- \*\*\*\*\* `remote_ip` in Caddy matches the TCP peer: with the peer address allowed, an `X-Forwarded-For` of `203.0.113.9` still got 200. A `client_ip` matcher, like the `/admin` rule, follows `trusted_proxies`. BunkerWeb's `allow`/`deny` include uses the real client address once `USE_REAL_IP=yes`, so it behaves like `client_ip`. For a pure peer check there is no equivalent while `USE_REAL_IP=yes`.
- Basic auth is **not enforced in detect mode**: no 401 and no log line. Check it in block mode. The realm differs (`restricted` in Caddy, `Restricted area` by default in BunkerWeb; `AUTH_BASIC_TEXT` sets it).
- Burst: stock Caddy has no rate limiter. BunkerWeb enables `USE_LIMIT_REQ` at `2r/s` for every client IP and, in detect mode, only logs `detected client IP ... limit for URL ...`. Block mode also ran the **bad-behavior ban**: a client that collects ten answers with status 400, 401, 403, 404, 405, 429 or 444 in 60 s is banned for 24 hours, and then every request returns 403. `bwcli bans` lists bans and `bwcli unban <ip>` clears one, run inside the BunkerWeb container. The counter keeps the last 60 s across probe runs, so wait a minute between two runs.
- HSTS: `header Strict-Transport-Security` answers on plain HTTP in Caddy; BunkerWeb sends it only on HTTPS (`src/common/core/headers/headers.lua`, the `ssl` check at line 95).
- Unknown host: with a host-matched site, Caddy answers any other `Host` with an empty 200. `DISABLE_DEFAULT_SERVER=yes` makes BunkerWeb answer 403 on HTTP and HTTPS (the default is `no`).

## Converted, each checked against the source

| Caddyfile                                                               | BunkerWeb setting that matched it                                                                          |
| ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `reverse_proxy echo:8080`, websockets included                          | `REVERSE_PROXY_HOST=http://echo:8080`, `REVERSE_PROXY_WS=yes`                                              |
| `header_up X-Custom-Source caddy`                                       | `REVERSE_PROXY_HEADERS=X-Custom-Source caddy`                                                              |
| `handle_path /api/*`                                                    | `REVERSE_PROXY_URL_2=^/api/`, `REVERSE_PROXY_INCLUDES_2` file `rewrite ^/api/(.*)$ /$1 break;`             |
| `@x { path /admin /admin/*; not client_ip 10.0.0.0/8 }` + `respond 403` | `REVERSE_PROXY_URL_3=^/admin(/\|$)`, include file `allow 10.0.0.0/8; deny all;`                            |
| `redir /old https://example.org/new 301`                                | `REDIRECT_FROM=^/old$`, `REDIRECT_TO`, `REDIRECT_TO_STATUS_CODE=301`                                       |
| `basic_auth /secure* { alice <bcrypt> }`                                | `USE_AUTH_BASIC=yes`, `AUTH_BASIC_LOCATION=/secure`, `AUTH_BASIC_USER`, `AUTH_BASIC_PASSWORD` (plain text) |
| `request_body { max_size 5MB }`                                         | `MAX_CLIENT_SIZE=5000000`                                                                                  |
| `header ...`                                                            | `X_FRAME_OPTIONS=DENY`, `CUSTOM_HEADER_1=X-Served-By: caddy`, `STRICT_TRANSPORT_SECURITY`                  |
| `encode gzip`                                                           | `USE_GZIP=yes`                                                                                             |
| `servers { trusted_proxies static private_ranges }`                     | `USE_REAL_IP=yes` (the default `REAL_IP_FROM` is the three private ranges)                                 |
| `rate_limit` module, `events 3`, `window 1m` on `/login`                | `LIMIT_REQ_URL_2=^/login$`, `LIMIT_REQ_RATE_2=3r/m`                                                        |

Checked separately, with the same method:

- Wrong first conversions that the run caught. `REVERSE_PROXY_URL_2=/api/` (plain prefix): `GET /api` answered `301` to `/api/`, where Caddy proxies it as `/api`; the regex `^/api/` leaves `/api` to the `/` entry. `REDIRECT_FROM=/old`: the generated nginx `location "/old"` is a prefix, so `/older` and `/old/x` are redirected too (confirmed on a throwaway entry, `/prefixold`, `/prefixolder`, `/prefixold/x`, all 301); Caddy's `redir /old` matches only that path.
- A path in `REVERSE_PROXY_HOST` replaces the whole URI instead of stripping a prefix: `REVERSE_PROXY_URL_5=/apipath/` with `http://echo:8080/` sent `GET /` upstream for both `/apipath/a/b` and `/apipath/`; `REVERSE_PROXY_URL_6=/prefix/` with `http://echo:8080/base/` sent `GET /base/` for `/prefix/a/b`. That earlier run used the URI rewrite include; the replacement regex result is below.
- **Correction:** that URI rewrite include marked matching requests internal and switched off BunkerWeb's Lua checks for the location. The replacement regex URL and host capture were subsequently run; see "Regex prefix conversion" below.
- `rate_limit` is a third-party module (`github.com/mholt/caddy-ratelimit` v0.1.0, built into Caddy 2.11.7 with `xcaddy`). Six `GET /login`, 1.1 s apart: Caddy 200, 200, 200, 429, 429, 429 with `Retry-After`; BunkerWeb in block mode with the two settings above: the same statuses, no `Retry-After` header, log `limited for URL /login (current rate = 4r/m and max rate = 3r/m)`. `caddy adapt` on a stock binary fails on that Caddyfile with `rate_limit is not a registered directive`, so run it with the binary the user actually runs.
- ACL order: `handle_path /api/*` runs before the `respond 403` that guards `/admin`, so `/api/admin` is proxied as `/admin` without the ACL. With a denied address in `X-Forwarded-For`: Caddy `/admin` 403, `/api/admin` 200; BunkerWeb converted `/admin` 403, `/api/admin` 200, the upstream saw `GET /admin` in both. The conversion keeps the hole, it does not add it.
- Websocket idle: Caddy had no idle limit (still open and echoing after 75 s). BunkerWeb closed the connection at 60.0 s, the default `REVERSE_PROXY_READ_TIMEOUT`. Raise it on the websocket entry.

## Automatic HTTPS and the certificate side

A second Caddy with `tls internal` and without `auto_https off`, reached by its container address with `curl --resolve`.

| Check                                | Caddy                                                                                      | BunkerWeb                                                                                          |
| ------------------------------------ | ------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| `GET http://caddy.example.com/x?a=1` | `308 Permanent Redirect`, `Location: https://caddy.example.com/x?a=1`                      | `301 Moved Permanently` (`AUTO_REDIRECT_HTTP_TO_HTTPS=yes`, certificate configured)                |
| certificate on 443                   | issuer `Caddy Local Authority - ECC Intermediate`, valid 12 hours                          | the same certificate with `USE_CUSTOM_SSL=yes` on the copied files (identical SHA-256 fingerprint) |
| where the files are                  | `/data/caddy/certificates/local/<domain>/<domain>.crt`, `.key`, `.json`, mode `0600`, root | read by the scheduler, which runs as uid 101                                                       |

- The copied certificate was mode `0600` and owned by uid 1000. The scheduler could not read it: `Error while executing job 'custom-cert' from plugin 'customcert'` and `Jobs failed in run_once(): customcert/custom-cert`, and BunkerWeb kept serving its self-signed certificate. After `chmod 644` and a scheduler restart the served certificate matched the Caddy file. That was a lab shortcut, not production advice: give scheduler uid/gid `101` access while keeping the private key at `600` and certificate at `644`.
- Caddy's `local` issuer certificates last 12 hours and chain to a private root, so this reuse is for the parallel run only. Production certificates come from `AUTO_LETS_ENCRYPT=yes`, which was not run here (the test host has no public name).
- With `auto_https off`, as in the table above, Caddy does not redirect HTTP to HTTPS and does not manage certificates. Both are Caddy defaults on a real site address, so the first table understates what a user's Caddy does.
- Not exercised: `tls { dns ... }` and wildcard issuance, the ZeroSSL fallback, `on_demand_tls`, several upstreams with `lb_policy`, upstream TLS verification, HTTP/3, `file_server` and `php_fastcgi`. They stay as written in `mapping.md`, from the setting definitions only.

## Regex prefix conversion

Run on 2026-10-06 with the same source configuration and echo upstream. The regex and host URI expression were copied from the mapping: `^/api/(.*)$` and `http://app:3000/$1$is_args$args`; only the lab upstream name and port changed. Source requests used HTTP; BunkerWeb requests used HTTPS. The comparison below checks status, redirect target and the upstream request line, not TLS or header parity. Requests were paced 1.1 s apart.

Initial mapping:

| Request                | Source upstream line or response     | BunkerWeb upstream line or response  | Match |
| ---------------------- | ------------------------------------ | ------------------------------------ | ----- |
| `/api/x/y?q=1&r=a%20b` | 200: `GET /x/y?q=1&r=a%20b HTTP/1.1` | 200: `GET /x/y?q=1&r=a%20b HTTP/1.1` | yes   |
| `/api`                 | 200: `GET /api HTTP/1.1`             | 200: `GET /api HTTP/1.1`             | yes   |
| `/api/`                | 200: `GET / HTTP/1.1`                | 200: `GET / HTTP/1.1`                | yes   |
| `/apix`                | 200: `GET /apix HTTP/1.1`            | 200: `GET /apix HTTP/1.1`            | yes   |
| `/api/a%2Fb`           | 200: `GET /a%2Fb HTTP/1.1`           | 200: `GET /a/b HTTP/1.1`             | no    |
| `/api/a%20b`           | 200: `GET /a%20b HTTP/1.1`           | 200: `GET /a%20b HTTP/1.1`           | yes   |
| `/api/caf%C3%A9`       | 200: `GET /caf%C3%A9 HTTP/1.1`       | 200: `GET /caf%C3%A9 HTTP/1.1`       | yes   |
| `/api//x`              | 200: `GET /x HTTP/1.1`               | 200: `GET /x HTTP/1.1`               | yes   |
| `/api/../admin`        | 200: `GET /api/../admin HTTP/1.1`    | 200: `GET /api/../admin HTTP/1.1`    | yes   |

The ordinary deep path and query matched. Bare `/api` and `/apix` went to the unstripped fallback; `/api/` became `/`. Caddy preserved `%2F` in `/api/a%2Fb`, while the regex capture sent `/a/b`: this form does **not** preserve Caddy's encoded-slash semantics. Space and UTF-8 encodings matched the upstream request line; doubled slashes became `/x` on both. `/api/../admin`, sent with `curl --path-as-is`, bypassed the stripping match on both and reached the fallback with its original request line. Keep the fallback and its controls; do not treat this as an ACL parity test. If the application distinguishes encoded slashes, mark that behavior as not carried over and resolve it before cutover; do not restore a URI rewrite to hide the mismatch.

### Checks in the regex location

`SECURITY_MODE=block` throughout; `USE_BAD_BEHAVIOR=no`. URI-parity probes initially had `USE_MODSECURITY=no` to separate routing from WAF decisions; then `USE_GREYLIST=yes` with `GREYLIST_IP=198.51.100.1` denied the actual test client. Greylist was disabled before the redirect and XSS run. The self-signed HTTPS service then used `AUTO_REDIRECT_HTTP_TO_HTTPS=yes` and `USE_MODSECURITY=yes`.

- HTTPS `/api/x/y?q=1`: `403`, `[ACCESS] denied access from greylist : not in greylist`.
- HTTP `/api/x/y?q=1`: `301`, `Location: https://caddy.example.com/api/x/y?q=1`; `[ACCESS] ssl redirect ... : redirect to HTTPS`.
- HTTPS `/api/x/y?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E`: `403`, CRS XSS rule `941100` and blocking rule `949110` (the run loaded CRS 4.29.0).
- HTTPS benign control `/api/x/y?q=clean`: `200`, upstream `GET /x/y?q=clean HTTP/1.1`.

Relevant log output (client address redacted; ModSecurity lines reduced to the message, rule and request):

```text
bunkerweb-1     | 2026/10/06 15:03:59 [warn] 310#310: *418 [ACCESS] denied access from greylist : not in greylist, client: <client-ip>, server: caddy.example.com, request: "GET /api/x/y?q=1 HTTP/2.0", host: "caddy.example.com"
bunkerweb-1     | 2026/10/06 15:04:27 [notice] 504#504: *615 [ACCESS] ssl redirect to https://caddy.example.com/api/x/y?q=1 : redirect to HTTPS, client: <client-ip>, server: caddy.example.com, request: "GET /api/x/y?q=1 HTTP/1.1", host: "caddy.example.com"
ModSecurity: XSS Attack Detected via libinjection; rule 941100; request: "GET /api/x/y?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E"
ModSecurity: Access denied with code 403 (phase 2); rule 949110; request: "GET /api/x/y?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E"
```

This proves greylist, the Lua HTTPS redirect and CRS on the tested regex path. It does not establish every Lua plugin or redirect-location security behavior.
