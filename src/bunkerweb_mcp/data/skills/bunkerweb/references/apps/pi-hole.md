# Pi-hole behind BunkerWeb

Template: https://github.com/bunkerity/bunkerweb-templates/tree/main/templates/pi-hole. Read at hub commit `4ba433a` (2026-09-19); the hub states no BunkerWeb version, it uses the 1.6 template format and every setting name exists at v1.6.15. The template was run as shipped, then changed where the live run showed a problem; see `## Verified live`.

- **Upstream and paths.** Proxy to the container's port `80`. Pi-hole v6 serves the UI on `/admin/` and the REST API on `/api/`. The template's README advises against serving it from the domain root, which widens the attack surface.
- **Root path.** Pi-hole answers `/` with `403` unless the `Host` header is its own name (`pi.hole`), so a browser opening the bare domain gets an error that also counts as a bad-behavior hit. Set `REVERSE_PROXY_CUSTOM_HOST` to `pi.hole` (no `_1` suffix: that setting is per service) and `/` redirects to `/admin/`. Or tell users to open `/admin/` directly.
- **Method allow-list.** The API uses `PATCH`, `PUT` and `DELETE` (settings, upstreams, log-out, deleting entries). The default `ALLOWED_METHODS` answers `405` to all of them in block mode and the template does not change it. Set `GET|POST|HEAD|OPTIONS|PUT|DELETE|PATCH` (`OPTIONS` was not exercised). This value drops the default `QUERY`; no flow here used it, and `|QUERY` at the end keeps it.
- **Upload size.** Teleporter backups are small, but `MAX_CLIENT_SIZE` defaults to `10m` and the template leaves it, so a larger archive gets `413`. A 22 MB archive imported with `100m`.
- **No WebSocket.** Pi-hole has no WebSocket endpoint; an upgrade request to `/admin/` got `502` with the template's `REVERSE_PROXY_WS` on. The dashboard does not need it.
- **Engine restarts.** A `PATCH /api/config` or a teleporter import restarts Pi-hole's engine (FTL) about half a second after it answers, and for about a second its web server refuses connections, so BunkerWeb answers `502`. That is the app, not a proxy fault: clients should retry once.
- **Real IP and bans.** The template assumes Cloudflare (`REAL_IP_FROM` ranges, `CF-Connecting-IP`). Change both, or switch `USE_REAL_IP` off. It counts `400 403 404 405 429 444` toward a ban at a threshold of `20`, and the rate limit is `20r/s` per URL. A script firing about 65 requests a second over four API URLs got `429` for a tenth of them; an open dashboard did not.

## CRS exclusions

The template removes whole rule tags (`attack-lfi`, `attack-rce`, `attack-xss`) and rule `920420` for all of `/api/` and `/admin/`. With none of that loaded, every flow below ran with no CRS hit except one: `PATCH /api/config` carrying a file-path value fires `930120` (OS file access). Four fields did it: `files.log.ftl`, `files.log.dnsmasq`, `files.log.webserver` and `webserver.paths.webroot`. The other `files.*`, `webserver.paths.*` and `webserver.tls.*` values did not. Custom config of type `modsec` (environment form `<server_name>_CUSTOM_CONF_MODSEC_pihole_paths`):

```text
SecRule REQUEST_FILENAME "@streq /api/config" "id:10000400,phase:1,pass,nolog,t:none,chain,\
    ctl:ruleRemoveTargetById=930120;ARGS:json.config.files.log.ftl,\
    ctl:ruleRemoveTargetById=930120;ARGS:json.config.files.log.dnsmasq,\
    ctl:ruleRemoveTargetById=930120;ARGS:json.config.files.log.webserver,\
    ctl:ruleRemoveTargetById=930120;ARGS:json.config.webserver.paths.webroot"
SecRule REQUEST_METHOD "@streq PATCH" "t:none,nolog"
```

List field names: a regex target (`ARGS:/re/`) loads and does nothing at 1.6.15. If you change another path-valued setting and get `403`, find the `930120` line in the log and add its `json.config...` name. A free-text comment holding a path such as `/etc/passwd` is still blocked (`930120`, `932160`), which is the intended behavior. Regex domains such as `(\.|^)ads?\.` and `select * from groups` in a comment passed with no exclusion.

## Verified live

Pi-hole 2026.09.0 (`pihole/pihole:2026.09.0`), BunkerWeb 1.6.15, tested 2026-10-06 with a self-signed certificate (`GENERATE_SELF_SIGNED_SSL=yes`) and the settings above.

| Flow                                                                  | Template as shipped, block | Settings fixed, block                     | Final, block |
| --------------------------------------------------------------------- | -------------------------- | ----------------------------------------- | ------------ |
| `/`, `/admin/`, login page, 12 assets                                 | `/` `403`                  | `/` `403`                                 | pass         |
| Login, session list, wrong password `401`                             | pass                       | pass                                      | pass         |
| 16 read endpoints, domains, groups, lists, clients CRUD               | `DELETE` `405`             | pass                                      | pass         |
| `PATCH` config (hosts, upstreams, paths), `PUT` and `DELETE` upstream | `405`                      | `403` on paths                            | pass         |
| Teleporter export, import, 22 MB import                               | `413` on the 22 MB file    | pass                                      | pass         |
| 80 paced polls, 100 burst polls, log-out                              | `405` on log-out           | `429` on log-out straight after the burst | pass         |

Boundary checks in block mode: the four listed fields passed; a `/etc/passwd` value in `dns.hosts` and in a deny-list comment got `403` (`930120`); a script tag in a query argument got `403` (`941100`, `941110`); a scanner User-Agent got `403` (`913100`); a plain request got `200`. In the final run the 80 paced polls all got `200` and the CRS logged nothing.

Not tested: DHCP, DNS answered through the proxy, the Cloudflare real-IP path, adlist updates and gravity runs.
