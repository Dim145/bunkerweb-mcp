# Verified live

Nginx Proxy Manager (NPM) 2.16.0 and BunkerWeb 1.6.15, 2026-10-06, each in front of its own `jmalloc/echo-server:v0.3.7`, one request set sent to both. NPM was set up only through its own API (first admin user, token, proxy hosts, access lists, a custom certificate, a redirection host, a stream, the default site), as an operator would. The hosts are `app` (custom locations, websockets, Block Common Exploits, an Advanced tab), `secure` (custom certificate, Force SSL, HSTS, an access list that needs both a password and an address), `either` (an access list that accepts either, Cache Assets), a redirection host and a TCP stream.

NPM trusts `X-Real-IP` from the private ranges, so the test sends `X-Real-IP: 10.1.2.3` (allowed) and `203.0.113.9` (denied), and BunkerWeb runs with `USE_REAL_IP=yes` and `REAL_IP_HEADER=X-Real-IP`. The probe pauses 1.1 s between requests, because BunkerWeb limits each client address to `2r/s` by default. `USE_BAD_BEHAVIOR=no` was set for the runs (see the traps).

## Proxy host `app`

| Request                                                     | NPM                              | BunkerWeb detect         | BunkerWeb block, defaults | BunkerWeb block, tuned |
| ----------------------------------------------------------- | -------------------------------- | ------------------------ | ------------------------- | ---------------------- |
| `GET /`                                                     | 200                              | 200                      | 200                       | 200                    |
| `GET /api/x?y=1` (custom location with Forward Path)        | upstream saw `/v2/x?y=1`         | same \*                  | same \*                   | same \*                |
| websocket handshake on `/.ws`, then one echoed frame        | 101                              | 101                      | 403 \*\*                  | 101                    |
| 4 MiB multipart upload / 6 MiB multipart upload             | 200 / 413                        | 200 / 413                | 200 / 413                 | 200 / 413              |
| 4 MiB `application/x-www-form-urlencoded` body              | 200                              | 200                      | 400 \*\*\*                | 200                    |
| 100 B `application/octet-stream` body                       | 200                              | 200                      | 403 \*\*\*\*              | 403 \*\*\*\*           |
| `/admin` from `10.1.2.3` / from `10.1.2.77`                 | 200 / 200                        | 200 / 200                | 200 / 200                 | 200 / 200              |
| `/admin` from `203.0.113.9` / `/admin/x` / `/administrator` | 403 / 403 / 403                  | 403 / 403 / 403          | 403 / 403 / 403           | 403 / 403 / 403        |
| `/old`                                                      | 301 to `https://example.org/new` | same                     | same                      | same                   |
| six `GET /login` with no pause                              | 200 x3, then 429 x3              | 200 x6                   | 200 x3, then 429 x3       | 200 x3, then 429 x3    |
| client sends `X-Forwarded-For: 198.51.100.9`, upstream saw  | the client address alone         | `198.51.100.9, <client>` | same                      | same                   |

Block Common Exploits, query string and user agent, same host:

| Request                                        | NPM | BunkerWeb detect | BunkerWeb block, defaults | BunkerWeb block, tuned |
| ---------------------------------------------- | --- | ---------------- | ------------------------- | ---------------------- |
| `?q=<script>x</script>`                        | 403 | 200              | 403                       | 403                    |
| `?id=1+union+select+version()`                 | 403 | 200              | 403                       | 403                    |
| `?f=/proc/self/environ`                        | 403 | 200              | 403                       | 403                    |
| `?GLOBALS[a]=1`                                | 403 | 200              | **200**                   | 403                    |
| `User-Agent: libwww-perl/6.0`                  | 403 | 200              | **200**                   | 403                    |
| `?id=1' OR '1'='1` (not in NPM's snippet)      | 200 | 200              | 403                       | 403                    |
| `?x=${jndi:ldap://a/b}` (not in NPM's snippet) | 200 | 200              | 403                       | 403                    |
| `?q=hello`                                     | 200 | 200              | 200                       | 200                    |

The rows that differ:

- \* The first run put `http://echo:8080/v2` in `REVERSE_PROXY_HOST_<n>` and the upstream saw `GET /v2`: the path and query of the request were gone. The runs in the table use `http://echo:8080` and an include file with `rewrite ^/api(/.*)?$ /v2$1 break;` on `REVERSE_PROXY_INCLUDES_<n>`.
- **Correction:** that URI rewrite include marked matching requests internal and switched off BunkerWeb's Lua checks for the location. The replacement regex URL and host capture were subsequently run; see "Regex prefix conversion" below.
- \*\* CRS rule `920440` ("URL file extension is restricted") fires on `/.ws`, the echo server's own path. The fix in the tuned run is a service-scoped `modsec-crs` config (scheduler variable `<server_name>_CUSTOM_CONF_MODSEC_CRS_<name>`) with `ctl:ruleRemoveById=920440` matched on that exact path; use [`bunkerweb-modsecurity-crs-tuning`](https://github.com/bunkerity/bunkerweb-skills/tree/main/skills/bunkerweb-modsecurity-crs-tuning) to write one. A path such as `/socket.io/` does not trip it.
- \*\*\* Rule `200002`: a non-file body above `MODSECURITY_REQ_BODY_NO_FILES_LIMIT` (default 131072) is refused with 400 in `block` and only logged in `detect`. The tuned run raised it to `5242880` on this service. Multipart uploads are not counted against it.
- \*\*\*\* Rule `920420` rejects content types outside its allowed list, `application/octet-stream` included. NPM passes any type. [`bunkerweb-modsecurity-crs-tuning`](https://github.com/bunkerity/bunkerweb-skills/tree/main/skills/bunkerweb-modsecurity-crs-tuning) covers the policy variable that widens it.
- The two **200** rows: CRS does not name `GLOBALS[`, and its rules do not read the user agent for `libwww-perl`. The tuned run closes them with `BLACKLIST_USER_AGENT` (log: `denied access from blacklist : UA is blacklisted`) and one `SecRule` of id `1000901` in a `modsec-crs` config. The rules CRS used for the other rows, in `detect`, were `941100`, `941110`, `941160` (script tag), `942100`, `942190`, `942360` (SQL), `930120`, `932130`, `932160`, `933135` (file access and shell), `944150` (Log4Shell) and `949110` (the anomaly score).
- Burst: the `/login` rule is a hand-written `limit_req` on the NPM side (`limit_req_zone` in `/data/nginx/custom/http_top.conf`, `limit_req zone=login burst=2 nodelay` in the location). BunkerWeb's `LIMIT_REQ_RATE_2=3r/m` gave the same 200, 200, 200, 429. In `detect` the log shows `detected client IP ... limit for URL /login (current rate = 4r/m and max rate = 3r/m)` and nothing is refused. BunkerWeb also limits `/` to `2r/s` for every client address; NPM has no such limit.
- Client address: NPM's custom locations set `X-Forwarded-For` to the client address alone (the spoofed value was dropped), BunkerWeb appends. An upstream that trusts the first entry of `X-Forwarded-For` sees the client's own claim behind BunkerWeb. Not run: overriding it with `REVERSE_PROXY_HEADERS`.

## Proxy hosts `secure` and `either`, HTTPS on both sides

| Request                                              | NPM                                                          | BunkerWeb detect                         | BunkerWeb block              |
| ---------------------------------------------------- | ------------------------------------------------------------ | ---------------------------------------- | ---------------------------- |
| `secure`, plain HTTP                                 | 301 to `https://secure.npm.example.com/`                     | same                                     | same                         |
| `secure`, no password, allowed address               | 401                                                          | 200                                      | 401                          |
| `secure`, no password, denied address                | 403                                                          | 200                                      | 403                          |
| `secure`, correct password, allowed / denied address | 200 / 403                                                    | 200 / 200                                | 200 / 403                    |
| `secure`, wrong password, allowed address            | 401                                                          | 200                                      | 401                          |
| `secure`, HSTS header                                | `max-age=63072000; preload` \*                               | `max-age=63072000` \*                    | `max-age=63072000` \*        |
| `either`, no password, allowed / denied address      | 200 / 401                                                    | 200 / 200                                | 200 / 401                    |
| `either`, correct password, denied / allowed address | 200 / 200                                                    | 200 / 200                                | 200 / 200                    |
| `either`, `Authorization` header seen by upstream    | none                                                         | the password, forwarded \*\*             | the password, forwarded \*\* |
| `either`, `GET /a.css`                               | `max-age=42958` and `Expires` (next 00:30)                   | `public, max-age=15552000`, no `Expires` | same                         |
| redirection host, `/some/path?a=1`                   | 301 to `https://example.org/some/path?a=1`                   | same                                     | same                         |
| unknown `Host`                                       | 200 "Congratulations" page, 404 once `default-site` is `404` | 403                                      | 403                          |
| TCP to the stream port, an HTTP request              | reaches the echo server                                      | same                                     | same                         |

- \* NPM's generated file for `secure` says `max-age=63072000;includeSubDomains; preload`, and the host served `max-age=63072000; preload`. All hosts' files declare `map $scheme $hsts_header`, so one nginx config holds four maps of one variable (`nginx -T`), and the served value matched the first host's. Read the header from the running host. BunkerWeb refused the same value in the first run: `Ignoring variable secure.npm.example.com_STRICT_TRANSPORT_SECURITY : value max-age=63072000; preload doesn't match regex ^(max-age=\d+(; includeSubDomains(; preload)?)?)?$`, and served its default, `max-age=63072000; includeSubDomains; preload`. The table uses the closest valid value.
- In `detect`, basic auth and the greylist let everything through. The log names what they would have done: `detected deny access from authbasic : missing Authorization header`, `... invalid password for user ...`, `detected deny access from greylist : not in greylist`. The include-file ACL on `/admin` is enforced by nginx and refused in `detect` too.
- \*\* NPM's "Pass Auth to Host" off stripped the header. On `secure`, `REVERSE_PROXY_HEADERS` set to `Authorization ""` did the same; `either` has no override.
- `either` matched NPM's "Satisfy Any" with `WHITELIST_IP` plus `USE_AUTH_BASIC`; `secure` matched "Satisfy All" with `USE_GREYLIST` plus `USE_AUTH_BASIC`.

## Traps seen in the runs

```text
REAL_IP_HEADER left at X-Forwarded-For, client sends X-Real-IP:   /admin from 10.1.2.3 -> 403, and 200 only with X-Forwarded-For: 10.1.2.3
NPM's apr1 hash pasted as AUTH_BASIC_PASSWORD:                    real password -> 401, the hash text as password -> 200
a host whose config fails nginx -t (a limit_req zone that did not exist yet): NPM wrote proxy_host/1.conf.err instead of 1.conf,
    the API showed meta.nginx_online=false and nginx_err "zero size shared memory zone "login"", the other hosts kept serving
default bad-behaviour ban, block run with many 4xx answers:        [BADBEHAVIOR] IP <client> is banned for 86400s (10/10) on server app...
                                                                   [ACCESS] IP <client> is banned with reason bad behavior (86307.7s remaining)
```

## Not exercised

Let's Encrypt issuance (HTTP and DNS challenge, the test names are not public), `.pem` splitting, HTTP/2, 404 Hosts, "Trust Forwarded Proto", deny-only access list entries, overriding `X-Forwarded-For`, and a Let's Encrypt certificate directory under `/etc/letsencrypt/` (the folder was empty).

## Regex prefix conversion

Run on 2026-10-06 with the same source configuration and echo upstream. The regex and host URI expression were copied from the mapping: `^/api(/.*)?$` and `http://portal-api:9000/v2$1$is_args$args`; only the lab upstream name and port changed. Source requests used HTTP; BunkerWeb requests used HTTPS. The comparison below checks status, redirect target and the upstream request line, not TLS or header parity. Requests were paced 1.1 s apart.

Initial mapping:

| Request                | Source upstream line or response        | BunkerWeb upstream line or response     | Match |
| ---------------------- | --------------------------------------- | --------------------------------------- | ----- |
| `/api/x/y?q=1&r=a%20b` | 200: `GET /v2/x/y?q=1&r=a%20b HTTP/1.1` | 200: `GET /v2/x/y?q=1&r=a%20b HTTP/1.1` | yes   |
| `/api`                 | 200: `GET /v2 HTTP/1.1`                 | 200: `GET /v2 HTTP/1.1`                 | yes   |
| `/api/`                | 200: `GET /v2/ HTTP/1.1`                | 200: `GET /v2/ HTTP/1.1`                | yes   |
| `/apix`                | 200: `GET /v2x HTTP/1.1`                | 200: `GET /apix HTTP/1.1`               | no    |
| `/api/a%2Fb`           | 200: `GET /v2/a/b HTTP/1.1`             | 200: `GET /v2/a/b HTTP/1.1`             | yes   |
| `/api/a%20b`           | 200: `GET /v2/a%20b HTTP/1.1`           | 200: `GET /v2/a%20b HTTP/1.1`           | yes   |
| `/api/caf%C3%A9`       | 200: `GET /v2/caf%C3%A9 HTTP/1.1`       | 200: `GET /v2/caf%C3%A9 HTTP/1.1`       | yes   |
| `/api//x`              | 200: `GET /v2/x HTTP/1.1`               | 200: `GET /v2/x HTTP/1.1`               | yes   |
| `/api/../admin`        | 403: no upstream                        | 200: `GET /api/../admin HTTP/1.1`       | no    |

After changing only the regex to `^/api(.*)$`:

| Request                | Source upstream line or response        | BunkerWeb upstream line or response     | Match |
| ---------------------- | --------------------------------------- | --------------------------------------- | ----- |
| `/api/x/y?q=1&r=a%20b` | 200: `GET /v2/x/y?q=1&r=a%20b HTTP/1.1` | 200: `GET /v2/x/y?q=1&r=a%20b HTTP/1.1` | yes   |
| `/api`                 | 200: `GET /v2 HTTP/1.1`                 | 200: `GET /v2 HTTP/1.1`                 | yes   |
| `/api/`                | 200: `GET /v2/ HTTP/1.1`                | 200: `GET /v2/ HTTP/1.1`                | yes   |
| `/apix`                | 200: `GET /v2x HTTP/1.1`                | 200: `GET /v2x HTTP/1.1`                | yes   |
| `/api/a%2Fb`           | 200: `GET /v2/a/b HTTP/1.1`             | 200: `GET /v2/a/b HTTP/1.1`             | yes   |
| `/api/a%20b`           | 200: `GET /v2/a%20b HTTP/1.1`           | 200: `GET /v2/a%20b HTTP/1.1`           | yes   |
| `/api/caf%C3%A9`       | 200: `GET /v2/caf%C3%A9 HTTP/1.1`       | 200: `GET /v2/caf%C3%A9 HTTP/1.1`       | yes   |
| `/api//x`              | 200: `GET /v2/x HTTP/1.1`               | 200: `GET /v2/x HTTP/1.1`               | yes   |
| `/api/../admin`        | 403: no upstream                        | 200: `GET /api/../admin HTTP/1.1`       | no    |

The original `^/api(/.*)?$` missed `/apix`: NPM forwarded it as `/v2x`, while BunkerWeb used the fallback `/apix`. The tested correction `^/api(.*)$` with the same `/v2$1$is_args$args` host expression matched that literal prefix behavior. Bare `/api` became `/v2`, `/api/` became `/v2/`, and the deep path/query, encoded slash, space, UTF-8 and doubled slash matched. Do not add a slash boundary unless changing NPM's behavior is intentional. `/api/../admin`, sent with `curl --path-as-is`, normalized outside the prefix location: NPM's separate `/admin` ACL returned `403`; the prefix-only BunkerWeb fixture used its fallback and returned `200` with the original request line. An allowed-address control on NPM returned `200` with that same original line. Carry the destination ACL and trusted-client rules separately; a matching prefix conversion does not preserve them. In compose, escape every `$` as `$$`.

### Checks in the regex location

`SECURITY_MODE=block` throughout; `USE_BAD_BEHAVIOR=no`. URI-parity probes initially had `USE_MODSECURITY=no` to separate routing from WAF decisions; then `USE_GREYLIST=yes` with `GREYLIST_IP=198.51.100.1` denied the actual test client. Greylist was disabled before the redirect and XSS run. The self-signed HTTPS service then used `AUTO_REDIRECT_HTTP_TO_HTTPS=yes` and `USE_MODSECURITY=yes`.

- HTTPS `/api/x/y?q=1`: `403`, `[ACCESS] denied access from greylist : not in greylist`.
- HTTP `/api/x/y?q=1`: `301`, `Location: https://app.npm.example.com/api/x/y?q=1`; `[ACCESS] ssl redirect ... : redirect to HTTPS`.
- HTTPS `/api/x/y?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E`: `403`, CRS XSS rule `941100` and blocking rule `949110` (the run loaded CRS 4.29.0).
- HTTPS benign control `/api/x/y?q=clean`: `200`, upstream `GET /v2/x/y?q=clean HTTP/1.1`.

Relevant log output (client address redacted; ModSecurity lines reduced to the message, rule and request):

```text
bunkerweb-1     | 2026/10/06 15:10:14 [warn] 409#409: *679 [ACCESS] denied access from greylist : not in greylist, client: <client-ip>, server: app.npm.example.com, request: "GET /api/x/y?q=1 HTTP/2.0", host: "app.npm.example.com"
bunkerweb-1     | 2026/10/06 15:10:34 [notice] 598#598: *838 [ACCESS] ssl redirect to https://app.npm.example.com/api/x/y?q=1 : redirect to HTTPS, client: <client-ip>, server: app.npm.example.com, request: "GET /api/x/y?q=1 HTTP/1.1", host: "app.npm.example.com"
ModSecurity: XSS Attack Detected via libinjection; rule 941100; request: "GET /api/x/y?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E"
ModSecurity: Access denied with code 403 (phase 2); rule 949110; request: "GET /api/x/y?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E"
```

This proves greylist, the Lua HTTPS redirect and CRS on the tested regex path. It does not establish every Lua plugin or redirect-location security behavior.
