# Mapping: ingress-nginx to BunkerWeb

Every BunkerWeb name here is verified at v1.6.15 (`src/common/core/<plugin>/plugin.json`, `src/autoconf/controllers/`). ingress-nginx annotation names are the controller's own: check them against the user's version. The column "Run" says whether the row was exercised against a live ingress-nginx `v1.15.1` beside BunkerWeb 1.6.15 (details in [verified-live.md](verified-live.md)) or only read from the settings files.

## Where a setting goes

- BunkerWeb settings are annotations on the same Ingress, `bunkerweb.io/<SETTING>: "<value>"`, under `ingressClassName: bunkerweb`. Every value is a quoted string. The Ingress `host` sets `SERVER_NAME`; that one cannot be an annotation.
- The controller writes `USE_REVERSE_PROXY=yes` and one `REVERSE_PROXY_HOST` and `REVERSE_PROXY_URL` pair per path. The Helm chart starts the numbering at nothing: the first path of an Ingress is the unsuffixed setting, the second is `_1`. So `bunkerweb.io/REVERSE_PROXY_WS: "yes"` on an Ingress with one path belongs to that path.
- Several Ingresses with the same host become one service. Their paths are renumbered by content, but each path keeps the numbered settings annotated on its own Ingress. A scalar setting (`MAX_CLIENT_SIZE`, `USE_GREYLIST`, `SECURITY_MODE`) is last-wins across them.
- An annotation can override what the controller derived: `REVERSE_PROXY_HOST` and `REVERSE_PROXY_URL` both worked that way.

## Mapping

| ingress-nginx                                                                 | BunkerWeb annotation                                                                                                                                  | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | Run        |
| ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| `ssl-redirect: "true"`, `force-ssl-redirect`                                  | `REDIRECT_HTTP_TO_HTTPS: "yes"`                                                                                                                       | Status `301`, ingress-nginx sends `308`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                            | yes        |
| `ssl-redirect: "false"`                                                       | `AUTO_REDIRECT_HTTP_TO_HTTPS: "no"`                                                                                                                   | `REDIRECT_HTTP_TO_HTTPS: "no"` alone is not enough: the auto redirect, on by default, still answers `301`.                                                                                                                                                                                                                                                                                                                                                                                                          | yes        |
| `proxy-body-size: 5m`                                                         | `MAX_CLIENT_SIZE: "5m"`, or `REVERSE_PROXY_MAX_CLIENT_SIZE: "5m"` for one path                                                                        | The ingress-nginx default is `1m`, BunkerWeb's `10m`. Set `MAX_CLIENT_SIZE: "1m"` on hosts that had no annotation, or accept `10m` on purpose.                                                                                                                                                                                                                                                                                                                                                                      | yes        |
| `proxy-connect-timeout`, `proxy-send-timeout`, `proxy-read-timeout` (seconds) | `REVERSE_PROXY_CONNECT_TIMEOUT`, `REVERSE_PROXY_SEND_TIMEOUT`, `REVERSE_PROXY_READ_TIMEOUT` with an `s` suffix                                        | Per path. A websocket idle past the read timeout is closed at that time on both sides.                                                                                                                                                                                                                                                                                                                                                                                                                              | yes (read) |
| websocket (always on in ingress-nginx)                                        | `REVERSE_PROXY_WS: "yes"`                                                                                                                             | Per path. Without it the upgrade fails.                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | yes        |
| `whitelist-source-range`                                                      | `USE_GREYLIST: "yes"`, `GREYLIST_IP: "10.0.0.0/8 192.168.0.0/16"`                                                                                     | An allow-list: other addresses get `403`. Host-wide. For one path add `GREYLIST_URI: "^(?!/admin(/\|$))"`, which admits every other URI.                                                                                                                                                                                                                                                                                                                                                                            | yes        |
| `denylist-source-range`                                                       | `BLACKLIST_IP`                                                                                                                                        |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | source     |
| `limit-rps`, `limit-rpm`                                                      | `USE_LIMIT_REQ: "yes"`, `LIMIT_REQ_URL: "/login"`, `LIMIT_REQ_RATE: "3r/s"`                                                                           | Per path (`LIMIT_REQ_URL` pairs with the rate). Refusal is `429`, not `503`. There is no burst: ingress-nginx allowed 17 of 30 immediate requests at `limit-rps: 3`, BunkerWeb 3 to 6. Setting `LIMIT_REQ_URL` replaces the default `/` rule at `2r/s` for that host.                                                                                                                                                                                                                                               | yes        |
| `limit-connections`                                                           | `USE_LIMIT_CONN`, `LIMIT_CONN_MAX_HTTP1`, `LIMIT_CONN_MAX_HTTP2`                                                                                      | On by default at 10 and 100.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | source     |
| `auth-type: basic`, `auth-secret`, `auth-realm`                               | `USE_AUTH_BASIC: "yes"`, `AUTH_BASIC_USER`, `AUTH_BASIC_PASSWORD`, `AUTH_BASIC_TEXT`, and `AUTH_BASIC_LOCATION: "/admin"` for one path                | `AUTH_BASIC_LOCATION` defaults to `sitewide`, which protects the whole host; a plain path is a prefix match (read from the plugin source, not run). The htpasswd hash cannot be imported: a hash given as the password is the password. Take the user names from the Secret and ask for new passwords. BunkerWeb forwards the `Authorization` header to the backend; add `REVERSE_PROXY_HEADERS: 'Authorization ""'` to drop it as ingress-nginx does. Several users: `AUTH_BASIC_USER_1`, `AUTH_BASIC_PASSWORD_1`. | yes        |
| `auth-url`, `auth-signin`                                                     | `REVERSE_PROXY_AUTH_REQUEST`, `REVERSE_PROXY_AUTH_REQUEST_SIGNIN_URL`                                                                                 |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | source     |
| `rewrite-target` with `use-regex`                                             | `REVERSE_PROXY_URL: "^/api(/\|$)(.*)$"` and `REVERSE_PROXY_HOST: "http://<svc>.<ns>.svc.cluster.local[:port]/$2?$args"`                               | The Ingress path stays a plain `/api`. Overriding the host drops the Service port the controller derived: write `:<port>` when it is not 80. `$N` are the capture groups, `?$args` keeps the query string (without it the query is dropped; with it an empty query leaves a trailing `?`).                                                                                                                                                                                                                          | yes        |
| `permanent-redirect`, `temporal-redirect`, `*-code`                           | `REDIRECT_FROM`, `REDIRECT_TO`, `REDIRECT_TO_STATUS_CODE`                                                                                             | Rule with a host and no `http` paths, or nginx fails with `duplicate location`.                                                                                                                                                                                                                                                                                                                                                                                                                                     | yes        |
| `pathType: Exact`                                                             | `REVERSE_PROXY_URL: "= /only"`                                                                                                                        | The default is a prefix: `/only/x` and `/onlyx` also matched.                                                                                                                                                                                                                                                                                                                                                                                                                                                       | yes        |
| `backend-protocol: HTTPS`                                                     | `REVERSE_PROXY_HOST: "https://<svc>.<ns>.svc.cluster.local[:port]"`                                                                                   | Or, for every host, the chart value `settings.kubernetes.serviceProtocol: https`. The backend certificate is not verified unless `REVERSE_PROXY_SSL_VERIFY` is `yes`.                                                                                                                                                                                                                                                                                                                                               | yes        |
| `backend-protocol: GRPC`                                                      | `USE_GRPC: "yes"`, `GRPC_HOST: "grpc://<svc>:<port>"`, `GRPC_URL`                                                                                     | The gRPC location always sets `modsecurity off`; ModSecurity does not inspect it.                                                                                                                                                                                                                                                                                                                                                                                                                                   | source     |
| `backend-protocol: GRPCS`                                                     | `USE_GRPC: "yes"`, `GRPC_HOST: "grpcs://<svc>:<port>"`, `GRPC_URL`                                                                                    | The gRPC location always sets `modsecurity off`; ModSecurity does not inspect it.                                                                                                                                                                                                                                                                                                                                                                                                                                   | source     |
| `enable-cors` and `cors-*`                                                    | `USE_CORS`, `CORS_ALLOW_ORIGIN` (a PCRE), `CORS_ALLOW_METHODS`, `CORS_ALLOW_HEADERS`, `CORS_ALLOW_CREDENTIALS`, `CORS_EXPOSE_HEADERS`, `CORS_MAX_AGE` | Three traps, see below.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | yes        |
| `proxy-buffering`, `proxy-request-buffering`                                  | `REVERSE_PROXY_BUFFERING`, `REVERSE_PROXY_REQUEST_BUFFERING`                                                                                          |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | source     |
| `upstream-vhost`                                                              | `REVERSE_PROXY_CUSTOM_HOST`                                                                                                                           |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | source     |
| `proxy-set-headers`, `custom-headers`                                         | `REVERSE_PROXY_HEADERS: "Name value;Name2 value2"` toward the backend, `CUSTOM_HEADER: "Name: value"` toward the client                               | The header values live in a ConfigMap in ingress-nginx; read it.                                                                                                                                                                                                                                                                                                                                                                                                                                                    | source     |
| `tls:` block with a Secret                                                    | the same `tls:` block                                                                                                                                 | The controller turns it into a custom certificate: BunkerWeb served the Secret's certificate.                                                                                                                                                                                                                                                                                                                                                                                                                       | yes        |
| ConfigMap `hsts`, `hsts-max-age`                                              | `STRICT_TRANSPORT_SECURITY: "max-age=31536000; includeSubDomains"`                                                                                    | ingress-nginx sends that by default on HTTPS; BunkerWeb's default is `max-age=63072000; includeSubDomains; preload`.                                                                                                                                                                                                                                                                                                                                                                                                | yes        |
| ConfigMap `use-forwarded-headers`                                             | `USE_REAL_IP: "yes"`, `REAL_IP_FROM`, `REAL_IP_HEADER`                                                                                                | The ACL and the rate limit then use the forwarded address.                                                                                                                                                                                                                                                                                                                                                                                                                                                          | yes        |
| `enable-modsecurity`, `enable-owasp-core-rules`                               | `USE_MODSECURITY`, `USE_MODSECURITY_CRS`                                                                                                              | On by default in BunkerWeb.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | source     |

### CORS

- Preflight needs `OPTIONS` in `ALLOWED_METHODS` (default `GET|POST|HEAD|QUERY`), or the preflight answers `405` in block mode. Write `bunkerweb.io/ALLOWED_METHODS: "GET|POST|HEAD|OPTIONS"`.
- With `CORS_DENY_REQUEST` at its default `yes`, a request whose `Origin` does not match answers `403`. That includes same-origin `POST` requests and websocket handshakes, which carry the page's own origin: put the site itself in the regex, `^https://(allowed|app)\.example\.com$`. ingress-nginx answers `200` without CORS headers instead.
- Do not set `CORS_DENY_REQUEST: "no"` to avoid that. With a regex origin BunkerWeb then sends `Access-Control-Allow-Origin` with whatever `Origin` the request had, including an unknown one.
- `Access-Control-Allow-Methods` and `-Credentials` are sent on the preflight only; ingress-nginx adds them to every response.

## Worked example

The host-wide settings sit on the Ingress of the first path; each other Ingress of the host adds its own path settings. This is the shape that passed the request set:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: app
  annotations:
    bunkerweb.io/REDIRECT_HTTP_TO_HTTPS: "yes"
    bunkerweb.io/MAX_CLIENT_SIZE: "5m"
    bunkerweb.io/REVERSE_PROXY_WS: "yes"
    bunkerweb.io/REVERSE_PROXY_READ_TIMEOUT: "5s"
    bunkerweb.io/USE_REAL_IP: "yes"
    bunkerweb.io/ALLOWED_METHODS: "GET|POST|HEAD|OPTIONS"
    bunkerweb.io/USE_CORS: "yes"
    bunkerweb.io/CORS_ALLOW_ORIGIN: "^https://(allowed|app)\\.example\\.com$"
spec:
  ingressClassName: bunkerweb
  tls:
    - hosts: [app.example.com]
      secretName: app-tls
  rules:
    - host: app.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: echo, port: { number: 80 } } }
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: app-admin
  annotations:
    bunkerweb.io/USE_GREYLIST: "yes"
    bunkerweb.io/GREYLIST_IP: "10.0.0.0/8"
    bunkerweb.io/GREYLIST_URI: "^(?!/admin(/|$))"
spec:
  ingressClassName: bunkerweb
  rules:
    - host: app.example.com
      http:
        paths:
          - path: /admin
            pathType: Prefix
            backend: { service: { name: echo, port: { number: 80 } } }
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: app-old
  annotations:
    bunkerweb.io/REDIRECT_FROM: "/old"
    bunkerweb.io/REDIRECT_TO: "https://example.org/new"
    bunkerweb.io/REDIRECT_TO_STATUS_CODE: "301"
spec:
  ingressClassName: bunkerweb
  rules:
    - host: app.example.com
```

The regex rewrite of `/api(/|$)(.*)` to `/$2`, on its own host:

```yaml
metadata:
  annotations:
    bunkerweb.io/REVERSE_PROXY_URL: "^/api(/|$)(.*)$"
    bunkerweb.io/REVERSE_PROXY_HOST: "http://echo.parity.svc.cluster.local/$2?$args"
spec:
  rules:
    - host: rewrite.example.com
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend: { service: { name: echo, port: { number: 80 } } }
```

## Not carried over

| ingress-nginx                                                                      | Why                                                                                                                                                                                                                                                     |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `configuration-snippet`, `server-snippet`, `stream-snippet`, `modsecurity-snippet` | Raw nginx. ingress-nginx rejects them in a default install, and BunkerWeb has no annotation for raw nginx. Put what is needed in a ConfigMap with `bunkerweb.io/CONFIG_TYPE` (`server-http`, `http`, `modsec-crs`, ...) and `bunkerweb.io/CONFIG_SITE`. |
| `canary`, `canary-*`, `mirror-*`                                                   | One backend Service per location.                                                                                                                                                                                                                       |
| `affinity`, `session-cookie-*`, `load-balance`, `upstream-hash-by`                 | No client-side balancing: BunkerWeb talks to the Service.                                                                                                                                                                                               |
| `proxy-next-upstream*`                                                             | No retry policy setting.                                                                                                                                                                                                                                |
| `ssl-passthrough`                                                                  | BunkerWeb terminates TLS.                                                                                                                                                                                                                               |
| `limit-burst-multiplier`                                                           | No burst setting.                                                                                                                                                                                                                                       |
| `server-alias`                                                                     | Add the alias as another `host` in the Ingress rules.                                                                                                                                                                                                   |

The controller ConfigMap keys are global defaults. Carry the ones that are set on to every host, or to the chart values `scheduler.features.*` and `scheduler.extraEnvs`.
