# Xen Orchestra behind BunkerWeb

Template: https://github.com/bunkerity/bunkerweb-templates/tree/main/templates/xen-orchestra. Read at hub commit `4ba433a` (2026-09-19); the hub states no BunkerWeb version, it uses the 1.6 template format and every setting name exists at v1.6.15. The template was run as shipped and then changed where the live run showed a problem; see `## Verified live`.

- **Upstream.** The container (`ronivay/xen-orchestra`) listens on port `80`. The template proxies `/` to it with `REVERSE_PROXY_WS` on. That is required: the web UI and every client talk JSON-RPC over a WebSocket at `/api/`, and the handshake got `101` through the proxy.
- **Entry paths.** `/` redirects to `/signin`; the old UI is under `/v5/` and the new one under `/v6/`, both redirects. The REST API is under `/rest/v0/` and takes the `authenticationToken` cookie or a token.
- **Method allow-list and size.** The template already sets `ALLOWED_METHODS` to `GET|POST|HEAD|OPTIONS|PUT|DELETE|PATCH` and `MAX_CLIENT_SIZE` to `100m`; nothing needed changing. That list drops the default `QUERY`, and no flow used it. The import URLs the API hands out (`$sendTo`) are `POST /api/<token>` and carry the file, so raise the size if your archives are bigger.
- **Security mode.** The template ships `SECURITY_MODE=block` (`templates/xen-orchestra/template.json` at hub commit `4ba433a`). It does not pin `detect`: the `detect` runs in the test setup were set by the test, not by the template. To follow the rollout rule, set `SECURITY_MODE=detect` yourself first, then switch back to `block`.
- **Rate limit.** The template limits `/jsonrpc` to `15r/s` and everything else to `6r/s` per URL. XO has no `/jsonrpc` URL (see below), so that limit never applies. Seven JSON-RPC calls a second over the WebSocket were never limited.
- **Bans.** The template sets `USE_BAD_BEHAVIOR` to `no`, so a client cannot ban itself with failed logins. Turning it on was not tested.

## CRS exclusions

The template's exclusion targets `/jsonrpc` and uses `ctl:ruleRemoveTargetById=<id>` with no target (`941130`, `942200`, `942440`, `942450`). Both parts do nothing, tested live:

- XO 5.211 does not serve `/jsonrpc`: a `POST` to it and to `/jsonrpcx` both got the same `302`. The JSON-RPC runs in WebSocket frames, and ModSecurity scores only the handshake request, not the frames. A SQL injection string and a script tag sent inside a frame (`server.add` with such a password) were accepted in block mode.
- `ctl:ruleRemoveTargetById` needs a `;TARGET` part. With none, rules `942360`, `942190` and `941110` still scored on `/jsonrpc` in both phase 1 and phase 2. The exclusion was a silent no-op.

What the CRS did score: rule `920420` (content type not allowed) on `POST /api/<token>`, the upload route that `xo.importConfig` and VM or disk import hand back, because the body is `application/octet-stream`. Custom config of type `modsec-crs` (phase 1; environment form `<server_name>_CUSTOM_CONF_MODSEC_CRS_xo_upload`; in a Compose `environment:` block write the `$` as `$$`):

```text
SecRule REQUEST_FILENAME "@rx ^/api/[A-Za-z0-9_-]{30,}$" \
    "id:10000500,phase:1,pass,nolog,t:none,chain,ctl:ruleRemoveById=920420"
SecRule REQUEST_METHOD "@streq POST" "t:none,nolog"
```

`PUT` on the same path, `POST /api/x`, `POST /rest/v0/vms` with that content type, and an odd content type on `/signin` all still got `403` (`920420`). A SQL injection form, a script tag in a query argument and a scanner User-Agent got `403`; a plain request got `200`. Drop the template's `/jsonrpc` rule and limit.

## Verified live

Xen Orchestra 5.211.0 (`ronivay/xen-orchestra:5.211.0`, with its own Redis), BunkerWeb 1.6.15, tested 2026-10-06 with a self-signed certificate (`GENERATE_SELF_SIGNED_SSL=yes`). No XenServer or XCP-ng pool was available.

| Flow                                                                                                        | Template as shipped, block | Final, block                                          |
| ----------------------------------------------------------------------------------------------------------- | -------------------------- | ----------------------------------------------------- |
| `/`, `/signin`, `/v5/`, `/v6/`, UI assets                                                                   | pass                       | pass                                                  |
| WebSocket `/api/` upgrade, sign in, wrong password rejected                                                 | pass                       | pass                                                  |
| JSON-RPC: list objects, users, servers, plugins, remotes; create and delete a user; add and remove a server | pass                       | pass                                                  |
| Token, then `/rest/v0/` reads with the token cookie, `401` without it                                       | pass                       | pass                                                  |
| `xo.exportConfig` download, then a 21 MB `POST` to the import URL                                           | `403` (`920420`)           | reaches XO, which rejects the junk archive with `500` |
| 40 JSON-RPC calls over one WebSocket in 6 seconds                                                           | pass                       | pass                                                  |
| Sign out                                                                                                    | pass                       | pass                                                  |

Not tested, because they need a pool: VM, host and pool operations, the console (a second WebSocket), backups to remotes, VM and disk import and export, and the XO Lite page.
