# Verified live

ingress-nginx `v1.15.1` (the minikube `ingress` addon, `registry.k8s.io/ingress-nginx/controller:v1.15.1`) and BunkerWeb 1.6.15 from Helm chart `1.1.0`, 2026-10-06, in one minikube cluster (Kubernetes 1.37.0, Docker driver). Both controllers served the same hosts in front of the same backends: `jmalloc/echo-server:v0.3.7`, and `nginx:1.29.1-alpine` with a self-signed certificate for the `backend-protocol: HTTPS` host. ingress-nginx served class `nginx` and BunkerWeb class `bunkerweb` (`settings.kubernetes.ingressClass`, chart `service.type: NodePort`). A single client sent the same request set to both; the ACL used `X-Forwarded-For` (`10.1.2.3` allowed, `203.0.113.9` denied) with `use-forwarded-headers` on ingress-nginx and `USE_REAL_IP` on BunkerWeb. The BunkerWeb annotations are the ones in [mapping.md](mapping.md), after the corrections below.

## Parity

Host `app.example.com`, HTTPS, four Ingresses (`/`, `/admin`, `/login`, `/old`), one TLS block.

| Request                                                | ingress-nginx                         | BunkerWeb detect                    | BunkerWeb block                    |
| ------------------------------------------------------ | ------------------------------------- | ----------------------------------- | ---------------------------------- |
| `GET /` over HTTP                                      | `308` to `https://app.example.com`    | `301` to `https://app.example.com/` | same as detect                     |
| `GET /` over HTTPS                                     | 200                                   | 200                                 | 200                                |
| HSTS header                                            | `max-age=31536000; includeSubDomains` | same, set by annotation             | same                               |
| websocket handshake on `/.ws`, one echoed text frame   | 101                                   | 101                                 | 101 \*                             |
| websocket idle 8 s, read timeout 5 s                   | closed at 5.0 s                       | closed at 5.0 s                     | closed at 5.0 s                    |
| 4 MiB / 6 MiB multipart upload, limit `5m`             | 200 / 413                             | 200 / 413                           | 200 / 413                          |
| `/admin` allowed address / denied address / `/admin/x` | 200 / 403 / 403                       | 200 / 200 / 200 \*\*                | 200 / 403 / 403                    |
| `/administrator`, denied address                       | 200                                   | 200                                 | 200                                |
| `/old`                                                 | `301` to `https://example.org/new`    | same                                | same                               |
| CORS preflight, allowed origin                         | 204, three CORS headers               | 200, three CORS headers             | 204, three CORS headers            |
| CORS `GET`, allowed origin                             | 200, three CORS headers               | 200, origin header only             | 200, origin header only            |
| CORS `GET`, unknown origin                             | 200, no CORS header                   | 200, origin echoed                  | 403 \*\*\*                         |
| 30 `GET /login` with no pause, `3` per second          | 17 x 200, then 13 x `503`             | 30 x 200 (logged)                   | 3 x 200, then 27 x `429`           |
| `GET /login` after 3 s                                 | 200                                   | 200                                 | 403, the client is banned \*\*\*\* |

Other hosts, same three columns where they differ.

| Request                                                                    | ingress-nginx               | BunkerWeb detect          | BunkerWeb block   |
| -------------------------------------------------------------------------- | --------------------------- | ------------------------- | ----------------- |
| `auth.example.com`: no credentials / wrong / right password                | 401 / 401 / 200             | 200 / 200 / 200 (logged)  | 401 / 401 / 200   |
| `Authorization` header seen by the backend                                 | absent                      | absent                    | absent            |
| `rewrite.example.com`: `/api/foo/bar?x=1`                                  | backend gets `/foo/bar?x=1` | same                      | same              |
| `/api`, `/api/`                                                            | backend gets `/`            | backend gets `/?`         | backend gets `/?` |
| `/apix/foo`, `/other`                                                      | 404, 404                    | 404, 404                  | 404, 404          |
| 2 MiB body, no body-size annotation (BunkerWeb: `MAX_CLIENT_SIZE` `1m`)    | 413                         | 413                       | 413               |
| `tlsback.example.com` (`backend-protocol: HTTPS`)                          | 200, backend saw `https`    | same                      | same              |
| `exact.example.com`: `/only`, `/only/x`, `/onlyx`                          | 200, 404, 404               | same                      | same              |
| `noredir.example.com` over HTTP (`ssl-redirect: "false"`)                  | 200                         | 200                       | 200               |
| `conflict.example.com`: 2 MiB to `/a` (1m), 2 MiB and 15 MiB to `/b` (20m) | 413, 200, 200               | same                      | same              |
| unknown Host                                                               | 404 on 80 and 443           | `301` on 80, `302` on 443 | same              |

The rows that differ:

- \* Block mode needed an exclusion. CRS rule `920440` ("URL file extension is restricted by policy") fires on the path `/.ws`, which is the echo server's own, and the handshake got `403` (anomaly rule `949110` follows). A path like `/socket` does not trip it. The fix that worked is a ConfigMap `ws-ext.conf` holding `SecRule REQUEST_URI "@streq /.ws" "id:1000900,phase:1,pass,nolog,ctl:ruleRemoveById=920440"`, with the annotations `bunkerweb.io/CONFIG_TYPE: "modsec-crs"` and `bunkerweb.io/CONFIG_SITE: "app.example.com"`. Use [`bunkerweb-modsecurity-crs-tuning`](https://github.com/bunkerity/bunkerweb-skills/tree/main/skills/bunkerweb-modsecurity-crs-tuning) to write real ones.
- \*\* Detect mode does not enforce the Lua checks. The log shows `detected deny access from greylist : not in greylist` for `/admin` and `/admin/x`, `detected deny access from authbasic : missing Authorization header`, `detected deny access from limit : detected client IP ... limit for URL /login (current rate = 4r/s and max rate = 3r/s)` and `detected deny access from cors : origin ... is not allowed`, and every request passed. The body-size limit (`413`), the redirects and the proxying are not Lua checks and applied in detect.
- \*\*\* `CORS_DENY_REQUEST` is `yes` by default and denies a request whose `Origin` does not match. The same check refuses same-origin `POST` requests and websocket handshakes (log line `origin https://app.example.com is not allowed`) unless the regex also matches the site itself. Setting `CORS_DENY_REQUEST` to `no` lets the unknown origin through but BunkerWeb then answers with `Access-Control-Allow-Origin: https://evil.example.net`, the request's own origin, so never use it with a regex.
- \*\*\*\* BunkerWeb bans a client after 10 error responses in 60 s (log `[BADBEHAVIOR] IP ... is banned for 86400s (10/10) on server app.example.com with scope service`). The 27 refusals above are enough. `kubectl -n bunkerweb exec deploy/scheduler-bunkerweb -- bwcli unban <ip>` lifts it.
- Rate limit: ingress-nginx allows a burst of `limit-rps` times five (15 here) and answers `503`; BunkerWeb counts per window with no burst and answers `429`. Between the two the number of requests that get through is not comparable.
- HTTPS redirect: `308` against `301`, and ingress-nginx leaves the trailing `/` off the root `Location`.
- Unknown Host: ingress-nginx answers its default backend's `404`; BunkerWeb answers from its default server, with a redirect. `DISABLE_DEFAULT_SERVER` changes that; it was not run here.
- `/api` reaches the backend as `/?` because the empty query string is appended after `?$args`.
- `Authorization`: BunkerWeb forwarded the header until `REVERSE_PROXY_HEADERS: 'Authorization ""'` was set. The htpasswd entry from the Secret does not work as a password: with the `$apr1$...` hash set as `AUTH_BASIC_PASSWORD`, the real password got `401` and the hash string itself got `200`.

## What the first conversion got wrong

Each of these was a real result before the mapping was corrected.

| Conversion                                                               | Result                                                                                                                                                                                                                    |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/old` listed as an Ingress path and as `REDIRECT_FROM`                  | `config check failed: nginx: [emerg] duplicate location "/old" in /etc/nginx/app.example.com/server-http/reverse-proxy.conf:74`, then `failing over to last working configuration`. No site updated.                      |
| `use-regex` path `/zz(/                                                  | $)(.*)` as the Ingress path                                                                                                                                                                                               | Generated as `location "/zz(/ | $)(.*)"`and`proxy_set_header X-Forwarded-Prefix "/zz(/ | $)(.*)"`; reload fails with `[emerg] invalid variable name`. The path `^/api(/ | $)(.*)$` is refused by the Kubernetes API (`must be an absolute path`). |
| `USE_GREYLIST` with `GREYLIST_IP` on the `/admin` Ingress                | The greylist applies to the host: in block mode every path answered `403` for an address outside `10.0.0.0/8`.                                                                                                            |
| `REDIRECT_HTTP_TO_HTTPS: "no"` for `ssl-redirect: "false"`               | HTTP still answered `301`.                                                                                                                                                                                                |
| No `MAX_CLIENT_SIZE` on the host that had no `proxy-body-size`           | A 2 MiB body got `200`, ingress-nginx answered `413` (`1m` default against `10m`).                                                                                                                                        |
| `pathType: Exact` with no override                                       | `/only/x` and `/onlyx` answered `200`.                                                                                                                                                                                    |
| `MAX_CLIENT_SIZE` `1m` on one Ingress, `20m` on another of the same host | Both paths got `20m`; controller log `Conflicting annotation for conflict.example.com: MAX_CLIENT_SIZE='1m' overwritten by '20m' from another Ingress/Route — last-wins`.                                                 |
| CORS without `OPTIONS` in `ALLOWED_METHODS`                              | Preflight `405` in block mode.                                                                                                                                                                                            |
| `configuration-snippet` on an ingress-nginx Ingress                      | `admission webhook "validate.nginx.ingress.kubernetes.io" denied the request: nginx.ingress.kubernetes.io/configuration-snippet annotation cannot be used. Snippet directives are disabled by the Ingress administrator`. |

Also observed: the chart sets `KUBERNETES_REVERSE_PROXY_SUFFIX_START=0` on the controller, so the first path is `REVERSE_PROXY_HOST` and the next ones `_1`, `_2`; with `/`, `/admin` and `/login` merged the generated service held `REVERSE_PROXY_URL`, `REVERSE_PROXY_URL_1` and `REVERSE_PROXY_URL_2`, each with its own annotated `REVERSE_PROXY_WS` or timeout. An Ingress of class `nginx` on a host no BunkerWeb Ingress named left no trace in the BunkerWeb service variables. The default install of ingress-nginx in minikube sets `hsts: "false"` in its ConfigMap, so HSTS only appeared once it was set back to `true`.

## Not run

`denylist-source-range`, `limit-rpm`, `limit-connections`, `auth-url`, gRPC backends, `proxy-buffering`, `upstream-vhost`, custom header ConfigMaps, `server-alias`, `DISABLE_DEFAULT_SERVER`, a `kubernetes.io/ingress.class` annotation instead of `ingressClassName`, and every cert-manager flow. Their BunkerWeb names are read from the plugin settings files, not exercised. Basic-auth and ACL results in detect mode were measured with one client address.

A note for anyone repeating this on a laptop: a wildcard DNS record on a host search domain made `<service>.<namespace>.svc.cluster.local` resolve to a public address from inside the pods (the name has fewer than five dots, so the search list is tried first), and the controller could not reach MariaDB. `getent hosts <service>.<namespace>.svc.cluster.local` from a pod shows it.
