# Seafile behind BunkerWeb

Template: https://github.com/bunkerity/bunkerweb-templates/tree/main/templates/seafile. Read at hub commit `4ba433a` (2026-09-19); the hub states no BunkerWeb version, it uses the 1.6 template format and every setting name exists at v1.6.15. Run live against BunkerWeb 1.6.15, see `## Verified live`.

- **Stop `X-Forwarded-Protocol`, or every request gets `400`.** BunkerWeb sends both `X-Forwarded-Proto` and `X-Forwarded-Protocol`. Seafile's web server (gunicorn) rejects a request that carries both, with a bare "Bad Request" page that never reaches the app log. The template does not handle this. Set `REVERSE_PROXY_HEADERS` to `X-Forwarded-Protocol ""`: a header you name there replaces BunkerWeb's default of the same name, and nginx omits a header whose value is empty.
- **Seafile side.** `SEAFILE_SERVER_PROTOCOL=https` and `SEAFILE_SERVER_HOSTNAME` set to the public name. With the 13.x image, WebDAV is off until `enabled = true` in `seafdav.conf` under the data volume, then restart the container.
- **Upload size and timeouts.** Uploads go through `/seafhttp/`. The template turns off response and request buffering and sets 1200 s timeouts with `MAX_CLIENT_SIZE=512m`; a 25 MB multipart upload, a chunked upload and a 25 MB WebDAV `PUT` all passed with those values.
- **Antibot.** The template turns on `USE_ANTIBOT=javascript` and lists the API and client paths in `ANTIBOT_IGNORE_URI`. Browser pages get the challenge. Anonymous visits to share links (`/f/<token>/`, `/d/<token>/`) are not in that list, so scripts and link previews are redirected to `/challenge` until a browser solves it. Add `^/f/` and `^/d/` if share links must work without JavaScript.
- **Notification server (websocket).** Seafile 13 ships it as a second container on port `8083`; the web client reaches it at `/notification`. The template has no route for it. Add a second proxy location: `REVERSE_PROXY_URL_1=/notification`, `REVERSE_PROXY_HOST_1=http://notification-server:8083`, `REVERSE_PROXY_WS_1=yes`, and set `ENABLE_NOTIFICATION_SERVER` and `NOTIFICATION_SERVER_URL` on Seafile. The HTTP ping and the websocket upgrade worked.
- **CRS exclusions, two, both scoped.** Custom config of type `modsec-crs` (environment form `<server_name>_CUSTOM_CONF_MODSEC_CRS_<name>`):

```text
SecRule REQUEST_METHOD "@streq PUT" "id:9005300,phase:1,pass,nolog,chain"
  SecRule REQUEST_FILENAME "@beginsWith /seafdav/" "ctl:ruleRemoveById=920420"
SecRule REQUEST_METHOD "@streq POST" "id:9005301,phase:1,pass,nolog,chain"
  SecRule REQUEST_FILENAME "@beginsWith /seafhttp/upload-aj/" \
   "setvar:'tx.restricted_headers_basic=/content-encoding/ /proxy/ /lock-token/ /if/ /x-http-method-override/ /x-http-method/ /x-method-override/ /x-middleware-subrequest/ /expect/'"
```

The first lets WebDAV clients `PUT` a file with its own content type (rule `920420`). The second lets the web UI's chunked upload send `Content-Range` (rule `920450`); the list is CRS 4.29's default minus `/content-range/`, so copy the current default from rule `901165` after a CRS upgrade.

- **Non-standard public port.** BunkerWeb sends `Host` without the port. A WebDAV `MOVE` whose `Destination` includes the port got `502`, and a login `POST` whose `Origin` includes it got `403`. This only shows up on a test port, not on 443.

## Verified live

Seafile 13.0.28 (`seafileltd/seafile-mc`), notification-server 13.0.21, MariaDB 10.11.19, Redis 8.8.3, BunkerWeb 1.6.15, tested 2026-10-06 with a self-signed certificate (`GENERATE_SELF_SIGNED_SSL=yes`).

| Flow                                                                   | Detect | Block |
| ---------------------------------------------------------------------- | ------ | ----- |
| Antibot challenge, web login, library page                             | pass   | pass  |
| API token, account info, create library, share link                    | pass   | pass  |
| 25 MB multipart upload, 4-chunk resumable upload, download with sha256 | pass   | pass  |
| WebDAV `PROPFIND` `MKCOL` `PUT` (25 MB, `image/jpeg`) `MOVE` `DELETE`  | pass   | pass  |
| Notification server ping and websocket upgrade                         | pass   | pass  |

Without the exclusions detect logged `920450` (`Content-Range`, chunked upload) and `920420` (WebDAV `PUT`). Block-mode boundary checks: another restricted header or a SQL injection string on the excluded paths, the same `Content-Type` on other paths or on `POST /seafdav/`, and `Content-Range` on other paths or methods all got `403`.

Not tested: the browser UI with JavaScript, WebDAV locking, desktop sync client, SeaDoc, Seafile AI, LDAP/SSO, notification messages after a subscribe, and load against the rate limits.
