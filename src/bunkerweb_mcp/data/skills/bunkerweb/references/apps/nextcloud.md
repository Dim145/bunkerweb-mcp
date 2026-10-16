# Nextcloud behind BunkerWeb

Template: https://github.com/bunkerity/bunkerweb-templates/tree/main/templates/nextcloud. Read at hub commit `4ba433a` (2026-09-19); the hub states no BunkerWeb version, it uses the 1.6 template format and every setting name exists at v1.6.15. Run live against BunkerWeb 1.6.15, see `## Verified live`.

- **Method allow-list.** WebDAV, CalDAV and CardDAV use verbs beyond GET and POST (`PROPFIND`, `PROPPATCH`, `MKCOL`, `MOVE`, `COPY`, `LOCK`, `UNLOCK`, `REPORT`, `MKCALENDAR` and others). Put them in `ALLOWED_METHODS`, or sync clients get `405`. Add them to the default `GET|POST|HEAD|QUERY` so that `QUERY` is kept.
- **Upload size.** `MAX_CLIENT_SIZE` also sets ModSecurity's request-body limit, and ModSecurity buffers bodies in memory. The template uses `512m`; a 25 MB `PUT` and a chunked upload of five 5 MB parts both went through at that value. Rely on Nextcloud's chunked uploads for big files.
- **Rate limits.** `LIMIT_REQ_RATE` defaults to `2r/s` for `/`, which throttles a normal Nextcloud. Set `LIMIT_REQ_URL=/` with a higher rate (the template uses `15r/s`) and per-path overrides (`LIMIT_REQ_URL_1`, `LIMIT_REQ_RATE_1`, and so on).
- **Bad behavior.** Leave `401` out of `BAD_BEHAVIOR_STATUS_CODES`: unauthenticated WebDAV probes answer `401`. The template's `400 403 405 444` means every WAF block also counts towards a ban.
- **CRS plugin, required.** On CRS v4 (the default) set `MODSECURITY_CRS_PLUGINS=nextcloud-rule-exclusions`. The scheduler downloads it at start, so it needs outbound HTTPS. With the plugin off, detect mode logged `920420` for `text/plain`, `application/octet-stream`, `text/calendar` and `text/vcard` bodies, and `920450` for the `If` header. A `modsec-crs` config setting `tx.crs_exclusions_nextcloud=1` only helps on CRS v3.
- **One gap the plugin leaves: `Lock-Token`.** `UNLOCK` under `/remote.php/dav/files/` sends the `Lock-Token` request header, and CRS rule `920450` restricts it. In block mode that request gets `403`. Add a custom config of type `modsec-crs` (environment form `<server_name>_CUSTOM_CONF_MODSEC_CRS_nextcloud_lock_token`). It drops `/lock-token/` from the restricted list for that method and path only:

```text
SecRule REQUEST_METHOD "@streq UNLOCK" "id:9005200,phase:1,pass,nolog,chain"
  SecRule REQUEST_FILENAME "@beginsWith /remote.php/dav/files/" \
   "setvar:'tx.restricted_headers_basic=/content-encoding/ /proxy/ /content-range/ /if/ /x-http-method-override/ /x-http-method/ /x-method-override/ /x-middleware-subrequest/ /expect/'"
```

The list is CRS 4.29's default minus `/lock-token/`. After a CRS upgrade, copy the new default from rule `901165` in `rules/REQUEST-901-INITIALIZATION.conf`. Two `ctl:ruleRemoveTargetById=920450;...` forms, one aimed at the `TX:header_name_920450_lock-token` variable and one at `REQUEST_HEADERS_NAMES:Lock-Token`, did not stop the hit, so do not use them.

- **Nextcloud side.** Name all three in the answer: set `TRUSTED_PROXIES` (the BunkerWeb network), `OVERWRITEPROTOCOL=https` and `NEXTCLOUD_TRUSTED_DOMAINS` (the service domain) on the container; `occ config:system:get` returned both values. Leave `USE_REAL_IP` off unless BunkerWeb itself sits behind another proxy.
- **Roll out in detect mode first.** Say in the answer: run with `SECURITY_MODE=detect`, read the BunkerWeb log while the sync clients (desktop and mobile) work, and switch to `block` only after that. The tested flows below passed in both modes.

## Verified live

Nextcloud 34.0.4 (`nextcloud:34.0.4-apache`, the Docker `stable` tag), PostgreSQL 17.11, Redis 8.8.3, BunkerWeb 1.6.15, tested 2026-10-06 with a self-signed certificate (`GENERATE_SELF_SIGNED_SSL=yes`), the template settings and the exclusion above.

| Flow                                                                               | Detect | Block |
| ---------------------------------------------------------------------------------- | ------ | ----- |
| Unattended install, login form, files and dashboard pages                          | pass   | pass  |
| OCS API (user, capabilities, app password, shares)                                 | pass   | pass  |
| WebDAV `PROPFIND` `MKCOL` `PUT` `MOVE` `COPY` `PROPPATCH` `REPORT` `LOCK` `UNLOCK` | pass   | pass  |
| 25 MB `PUT` and chunked upload, sha256 checked                                     | pass   | pass  |
| CalDAV and CardDAV `PUT`, `REPORT`, `MKCALENDAR`                                   | pass   | pass  |
| Public share link create, page and download                                        | pass   | pass  |

Detect mode logged one rule, `920450` on `Lock-Token`, and block mode logged none. Boundary checks in block mode: another restricted header (`Proxy`, `X-HTTP-Method-Override`) on the same method and path got `403`; `Lock-Token` on `PROPFIND`, on `UNLOCK` for a calendar path and on `UNLOCK` for `/status.php` got `403`; a SQL injection string on the excluded path got `403` (`942100`).

Not tested: the browser UI with JavaScript, the `notify_push` websocket (a separate app and service), Talk, office suites, LDAP, mail, Let's Encrypt, and load against the rate limits.
