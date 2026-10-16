# Verified live

Traefik v3.7.13 and BunkerWeb 1.6.15 (autoconf, labels), 2026-10-06, both in front of `jmalloc/echo-server:v0.3.7`, the same request set sent to each. Two sites, so both places Traefik keeps configuration were converted:

- **Site A**, Docker labels. Routers `a-web` (`web`, `redirectscheme`), `a` (`websecure`, TLS; middlewares `secure-headers@file`, `size-limit@file`, `gz@file` and a `redirectregex`), `a-admin` (`PathPrefix(/admin)`, `ipallowlist`), `a-login` (`Path(/login)`, `ratelimit` 3 per minute, burst 3), `a-secure` (`PathPrefix(/secure)`, `basicauth`), `a-api` (`PathPrefix(/api)`, `stripprefix`).
- **Site B**, file provider (`dynamic.yml`), the same shape with three differences: `average=30` for the rate limit, a `{SHA}` basic-auth hash, and a `b-plain` router that serves plain HTTP with no redirect and carries no `/admin`, `/secure`, `/login` or `/api` router.

The client reaches `/admin` with `X-Forwarded-For: 10.1.2.3` (allowed) or `203.0.113.9` (denied). Traefik trusts the header from the Docker gateway (`forwardedHeaders.trustedIPs`) and takes the first address that is not in `172.16.0.0/12` (`ipStrategy.excludedIPs`); BunkerWeb uses `USE_REAL_IP=yes`. The BunkerWeb runs used `USE_BAD_BEHAVIOR=no` (see "Other results") and a request pace of 1.1 s, which keeps three requests to one URL under the default `2r/s` limit.

## Site A over HTTPS

| Request                                                         | Traefik                               | BunkerWeb detect                | BunkerWeb block                |
| --------------------------------------------------------------- | ------------------------------------- | ------------------------------- | ------------------------------ |
| `GET /`                                                         | 200                                   | 200                             | 200                            |
| `Strict-Transport-Security`, custom response and request header | all present                           | same                            | same                           |
| `/old`                                                          | 301 to `https://example.org/new`      | same                            | same                           |
| websocket handshake on `/.ws`, one echoed text frame            | 101                                   | 101                             | 403 \*, 101 with the exclusion |
| 4 MiB multipart / 6 MiB multipart                               | 200 / 413                             | 200 / 413                       | 200 / 413                      |
| 4 MiB `application/x-www-form-urlencoded`                       | 200                                   | 200                             | 400 \*\*, 200 once raised      |
| 100 B `application/octet-stream`                                | 200                                   | 200                             | 403 \*\*\*                     |
| `/admin` allowed address / denied address                       | 200 / 403                             | 200 / 200 \*\*\*\*              | 200 / 403                      |
| `/admin/x` and `/administrator`, denied address                 | 403, 403                              | 200, 200 \*\*\*\*               | 403, 403                       |
| `/`, denied address                                             | 200                                   | 200                             | 200                            |
| `/secure` no credentials / good / bad                           | 401 / 200 / 401                       | 200 / 200 / 200 \*\*\*\*        | 401 / 200 / 401                |
| `/secure/x` good credentials, `/secure-not` without             | 200, 401                              | 200, 200 \*\*\*\*               | 200, 401                       |
| `/api/x?q=1`, path the upstream saw                             | `/x?q=1`                              | `/x?q=1`                        | `/x?q=1`                       |
| `Accept-Encoding: gzip`, 3 KB response                          | gzip                                  | gzip                            | gzip                           |
| six `GET /login` with no pause                                  | 200 x3, then 429 x3                   | 200 x6 \*\*\*\*                 | 200 x3, then 429 x3            |
| `GET /` over HTTP                                               | 301 to `https://a.example.com:18983/` | 301 to `https://a.example.com/` | same                           |

- \* Rule `920440` ("URL file extension is restricted by policy") matches the echo server's `/.ws` path, then `949110` blocks (the same ids as the Apache run). A service label `bunkerweb.CUSTOM_CONF_MODSEC_CRS_ws-ext=SecRule REQUEST_URI "@streq /.ws" "id:1000900,phase:1,pass,nolog,ctl:ruleRemoveById=920440"` gave 101 and the echo in block mode. A path like `/socket` does not trip the rule.
- \*\* Rule `200002` ("Failed to parse request body"): non-file bodies above `MODSECURITY_REQ_BODY_NO_FILES_LIMIT` (default 131072) get 400 in block mode. The label `bunkerweb.MODSECURITY_REQ_BODY_NO_FILES_LIMIT=5242880` let the same body through. Multipart uploads are not counted.
- \*\*\* Rule `920420` ("Request content type is not allowed by policy", CRS 4.29.0) rejects `application/octet-stream`. Traefik passes any type. See [`bunkerweb-modsecurity-crs-tuning`](https://github.com/bunkerity/bunkerweb-skills/tree/main/skills/bunkerweb-modsecurity-crs-tuning) for the policy variable.
- \*\*\*\* In detect the greylist, basic auth and the request limit only log: `detected deny access from greylist : not in greylist`, `detected deny access from authbasic : missing Authorization header` and `detected deny access from limit`. Nothing is refused until the service is switched to block. The nginx-level checks (`allow`/`deny`, `MAX_CLIENT_SIZE`, the HTTPS redirect) do not wait for block.
- The redirect location differs only because the test Traefik sends the client to port 18983 (`redirectscheme.port`); BunkerWeb has no port option.
- The six-request `/login` row is `LIMIT_REQ_RATE_2=3r/m` against `average=3`, `period=1m`, `burst=3`.

## Site B

Over HTTPS, B matched A on every row above except the rate limit. What else differs:

| Request                                                                     | Traefik                                      | BunkerWeb detect            | BunkerWeb block    |
| --------------------------------------------------------------------------- | -------------------------------------------- | --------------------------- | ------------------ |
| six `GET /login`, `average=30`, `burst=3`                                   | 200 x3, then 429 x3                          | 200 x6                      | 200 x6             |
| `/admin` denied address, `allow`/`deny` include on a `/admin` location      | 403                                          | 403                         | 403                |
| plain HTTP: `/admin` denied address, `/secure` no credentials, `/api/x?q=1` | 200, 200, upstream saw `/api/x?q=1` \*\*\*\* | 403, 200 \*\*\*\*, `/x?q=1` | 403, 401, `/x?q=1` |
| plain HTTP `GET /`, default `AUTO_REDIRECT_HTTP_TO_HTTPS`                   | 200                                          | 301 to HTTPS                | 301 to HTTPS       |
| plain HTTP `GET /`, `AUTO_REDIRECT_HTTP_TO_HTTPS=no`                        | 200                                          | 200                         | 200                |

- A `30r/m` limit does not fire on six requests in under a second; Traefik's burst of 3 does. Keep the burst in mind when the Traefik value is large.
- Traefik applied `/admin`, `/secure`, `/login` and `/api` only on the HTTPS router (the `web` router of B has none of them). BunkerWeb applies a setting to both ports, so the plain-HTTP side is stricter after conversion.
- B's `{SHA}` hash was replaced by a plain-text `AUTH_BASIC_PASSWORD`; the same user and password then gave 401 / 200 / 401 for no, good and bad credentials in block, as on Traefik.

## What the first conversion got wrong

The mapping that existed before this run was applied first and probed, then corrected:

- `ipallowlist` mapped to `USE_GREYLIST=yes` plus `GREYLIST_IP=10.1.2.3`, on a router that covered only `/admin`: BunkerWeb denied the other address on every path (the first probe of site A: `GET /` logged `detected deny access from greylist : not in greylist` in detect, and the first block run answered 403 on `/`, `/secure`, uploads and the websocket). The label that scopes it is `GREYLIST_URI=^(?!/admin)`; an include with `allow`/`deny` on a `/admin` location also worked.
- `stripprefix` mapped to `REVERSE_PROXY_INCLUDES_2=/includes/strip-api.conf` holding `rewrite ^/api/(.*)$ /$1 break;`. The URI rewrite marks the request internal, so BunkerWeb skips its whole Lua access phase. The prefix was stripped (`/x?q=1`), but for that location the greylist did not deny a client outside the list (200 against 403 elsewhere), the plain-HTTP request was not redirected to HTTPS (200 against 301 elsewhere), and the access-phase checks left no log line. ModSecurity still ran: a `<script>` query on `/api/x` got 403. The regex location in the mapping fixed it: `/api/x` over HTTP answered 301 again.
- `REVERSE_PROXY_HOST_2=http://echo-b:8080/` (a trailing path, nginx's own way to strip a prefix) made the upstream see `/` for `/api/x?q=1`: the upstream is held in a variable, and its path replaces the request URI.
- The regex location has two edges: a bare `/api` does not match `^/api/(.*)$` and falls to the `/` location unstripped, and BunkerWeb adds no `X-Forwarded-Prefix` for a regex URL. Traefik's `stripprefix` sends `/api`; a plain `/api` BunkerWeb location sends `/api`; the `/` location sends `/`, which Traefik does not.

## Other results

- **Bad behavior.** On the first block run the probe client was banned: `[BADBEHAVIOR] IP <docker-gateway-ip> is banned for 86400s (17/10) on server a.example.com with scope service`, and every later request got 403 until `bwcli unban <docker-gateway-ip> -service a.example.com`. A clean run on one service, 14 requests to `/secure` without credentials 0.6 s apart: `[401, 401, 429, 429, 429, 401, 401, 429, 429, 429, 401, 403, 403, 403]`. The 429s are the default `2r/s` limit, and the ban landed on the 11th bad status (`11/10`). Then `GET /` on that service answered 403 and the other service answered normally. Traefik bans nothing.
- **Unknown Host.** Traefik `404` on both ports. BunkerWeb `200` with its placeholder page on both ports; with `DISABLE_DEFAULT_SERVER: "yes"` on the scheduler, `403` on both and the known host still `200`.
- **Headers the upstream saw.** Traefik sent `X-Forwarded-For`, `-Host`, `-Port`, `-Proto`, `-Server` and `X-Real-Ip`. The generated BunkerWeb location sends `X-Forwarded-For`, `-Host`, `-Proto`, `-Protocol`, `-Prefix` and `X-Real-IP`, and no `-Port` or `-Server`.
- **Inventory.** `GET /api/rawdata` on the Traefik dashboard port returned `routers`, `middlewares` and `services` for both providers with the `@docker` and `@file` suffixes, each middleware's settings (the `rateLimit` as `average: 3, period: 1m0s, burst: 3`, the `basicAuth` hash) and its `usedBy` routers.
- **Autoconf.** The stack in `mapping.md` came up healthy in about 50 s. Labels on the application containers became services on the first start and were re-applied by `docker compose up -d` on a label change, with nginx reloaded within 30 s. The `bunkerweb.SECURITY_MODE` label switched one service at a time.
- **Teardown.** `docker compose down -v` on the Traefik project, the BunkerWeb stack and the application project left nothing named `bwsrc-17c-*`.

## Not run

`certresolver` and `acme.json` (the BunkerWeb side used `GENERATE_SELF_SIGNED_SSL`), DNS challenge, `forwardAuth`, `retry`, `circuitbreaker`, `inFlightReq`, `passTLSClientCert`, `replacePathRegex`, `HostRegexp`, several `Host()` names in one rule, `brotli`, `AUTH_BASIC_USER_<n>` with several users, a `redirectregex` that matches more than the path, and any Traefik version except v3.7.13.
