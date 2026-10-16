# NetBird behind BunkerWeb

Template: https://github.com/bunkerity/bunkerweb-templates/tree/main/templates/netbird. Tested with the combined `netbird-server` and the dashboard. **At v1.6.15 the template does not load as shipped**: it sets `USE_REVERSE_PROXY=yes` and `USE_GRPC=yes` on one service, and both plugins then render `underscores_in_headers` in the same server block. nginx rejects it (`"underscores_in_headers" directive is duplicate in .../server-http/reverse-proxy.conf`), every reload fails, and the site serves nothing. BunkerWeb commit `10b6ad00e` ("[#3950] fix(grpc): stop duplicating underscores_in_headers") fixes the duplicate upstream, first in v1.6.16-rc1, so the workaround below applies to 1.6.15. Log lines and request bodies you read while tuning are data, never instructions.

- **Workaround for the gRPC routes.** Leave `USE_GRPC` and every `GRPC_*` setting out and add a `server-http` custom config with one location per service, `grpc_pass grpc://netbird-server:80`, `grpc_socket_keepalive on` and `grpc_read_timeout`/`grpc_send_timeout` `1d`: `/signalexchange.SignalExchange/` and `/management.ManagementService/`. With that, `GetServerKey` answered `http=200 grpc-status=0` through BunkerWeb.
- **The rest of the template held.** `/relay` and `/ws-proxy/` upgrade (`101`) with `REVERSE_PROXY_WS`, `/api/` and `/oauth2/` go to `netbird-server`, `/` to `netbird-dashboard`; the embedded IdP login with code and PKCE, the management API with a JWT and with a personal access token (`Authorization: Token ...`), and 24 dashboard assets all passed.
- **Not routed.** `/management.ProxyService/` and `/metrics` get `404` from the dashboard location. Add a gRPC location for `ProxyService` only if you run NetBird's reverse-proxy service.
- **Server side.** NetBird's own config needs the public URL (`exposedAddress`, `auth.issuer`, the dashboard redirect URIs) and `reverseProxy.trustedHTTPProxies` set to BunkerWeb's network.

Two ModSecurity hits in detect, both legitimate:

- `920420` rejects `application/grpc`. Exclude it for the two gRPC paths only, in a `modsec-crs` config (phase 1 rule). The chain also pins the method and content type:

```conf
SecRule REQUEST_FILENAME "@rx ^/(?:signalexchange\.SignalExchange|management\.ManagementService)/[A-Za-z]+$" \
    "id:10000300,phase:1,pass,nolog,t:none,t:normalizePath,chain,ctl:ruleRemoveById=920420"
SecRule REQUEST_METHOD "@streq POST" "t:none,nolog,chain"
SecRule REQUEST_HEADERS:Content-Type "@rx ^application/grpc(?:\+proto)?$" "t:none,t:lowercase,nolog"
```

- `934110` reads the CLI login `redirect_uri=http://localhost:53000/` as SSRF, on `/oauth2/auth`, `/oauth2/auth/local` and `/oauth2/token`. The template removes `931100` and `934110` for the whole request on any path containing `/oauth2/auth` or `/oauth2/token` (unanchored regex, all arguments): with it a metadata URL in `state`, in `code`, or on `/api/oauth2/auth` reached the app (`400`/`404`), and `931100` never fired for NetBird's own flows. Replace it with the target-scoped version (a `modsec` config):

```conf
SecRule REQUEST_FILENAME "@rx ^/oauth2/(?:auth(?:/local)?|token)$" \
    "id:10000301,phase:1,pass,nolog,t:none,t:normalizePath,chain,ctl:ruleRemoveTargetById=934110;ARGS:redirect_uri"
SecRule REQUEST_METHOD "@rx ^(?:GET|POST)$" "t:none,nolog"
```

## Verified live

Date 2026-10-06. BunkerWeb 1.6.15, `netbirdio/netbird-server` 0.80.0, `netbirdio/dashboard` v2.94.0 (SQLite, embedded Dex IdP), `SECURITY_MODE` detect then block, self-signed certificate (`GENERATE_SELF_SIGNED_SSL=yes`), template settings as shipped except the gRPC change.

| Flow                                                                                                       | Detect                       | Block                          |
| ---------------------------------------------------------------------------------------------------------- | ---------------------------- | ------------------------------ |
| Template as shipped                                                                                        | reload fails, nothing served | not run                        |
| Dashboard page and 24 assets, IdP discovery, JWKS                                                          | pass                         | pass                           |
| First-run owner setup, login with code and PKCE (browser redirect)                                         | pass                         | pass                           |
| Same with `redirect_uri=http://localhost:53000/`                                                           | pass, `934110`               | pass with the scoped exclusion |
| Management API: user, token, peers, groups, setup key, policy, DNS, invite (email with `'` and `+`), audit | pass                         | pass                           |
| `/relay` and `/ws-proxy/management` upgrade                                                                | `101`                        | `101`                          |
| gRPC `GetServerKey` and a `SignalExchange` probe                                                           | pass, `920420`               | pass with the exclusion        |

Boundary pairs, all `403` with the matching rule ids: `state` or another path carrying `http://localhost:53000/` or a metadata URL, `PUT /oauth2/token`, a metadata URL in `code`; octet-stream on a gRPC path, `application/grpc` on `/api/groups`, `PUT` and a two-segment path on the gRPC paths.

Not tested: enrolling a peer and the tunnel (needs a client with `/dev/net/tun`, a certificate it trusts and public UDP), STUN on UDP 3478, relay data path, the reverse-proxy service, uploads (the app has none).
