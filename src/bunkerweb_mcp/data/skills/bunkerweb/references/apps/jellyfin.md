# Jellyfin behind BunkerWeb

Template: https://github.com/bunkerity/bunkerweb-templates/tree/main/templates/jellyfin. Read at hub commit `4ba433a` (2026-09-19); the hub states no BunkerWeb version, it uses the 1.6 template format and every setting name exists at v1.6.15. Run live against BunkerWeb 1.6.15, see `## Verified live`.

- **Streaming.** Turn off response buffering (`REVERSE_PROXY_BUFFERING=no`) and lengthen the read and send timeouts (the template uses `300s`). A 32 MB direct stream, a ranged request (`206`) and an HLS playlist all went through.
- **WebSockets.** `/socket` needs its own reverse-proxy location with `REVERSE_PROXY_WS` on, using the numbered form (`REVERSE_PROXY_URL_1`, `REVERSE_PROXY_HOST_1`, `REVERSE_PROXY_WS_1`). Jellyfin 12.2 itself answers `403` to a socket request that carries only `?api_key=`; with an `Authorization: MediaBrowser Token="..."` header the upgrade returned `101` and the server pushed frames.
- **Upstream.** The container listens on `8096`, so `REVERSE_PROXY_HOST` is `http://jellyfin:8096`.
- **Upload size.** `MAX_CLIENT_SIZE=20M` in the template is enough for profile and library images: a 21 MB body got `413` from BunkerWeb, a small image `204`.
- **CRS exclusion 1: `/web/config.json`.** Rule `930130` flags that file as a restricted file, and the web client requests it on every load. The template's second rule, for `/web/node_modules.history.bundle.js`, logged nothing at Jellyfin 12.2 when removed; keep it only for older Jellyfin. A scoped version of the first one, as a custom config of type `modsec-crs` (environment form `<server_name>_CUSTOM_CONF_MODSEC_CRS_<name>`):

```text
SecRule REQUEST_FILENAME "@streq /web/config.json" \
 "id:9005400,phase:1,pass,nolog,ctl:ruleRemoveTargetById=930130;REQUEST_FILENAME"
```

- **CRS exclusion 2: image uploads.** The profile picture is posted with the image's own `Content-Type`, which rule `920420` rejects. The template does not cover this. In the same config, extend the allowed list for that method and path only:

```text
SecRule REQUEST_METHOD "@streq POST" "id:9005401,phase:1,pass,nolog,chain"
  SecRule REQUEST_FILENAME "@rx ^/Users/[^/]+/Images/" \
   "setvar:'tx.allowed_request_content_type=|application/x-www-form-urlencoded| |multipart/form-data| |text/xml| |application/xml| |application/soap+xml| |application/json| |image/png| |image/jpeg| |image/gif| |image/webp|'"
```

The list is CRS 4.29's default plus four image types; read the current default in `REQUEST-901-INITIALIZATION.conf` after a CRS upgrade. `/Items/<id>/Images/` takes the same kind of upload but was not tested.

- **Bad behavior and Docker.** With the defaults, a run of `401` and `404` answers (a wrong password, a client polling before it logs in) fills the ban counter: the log showed `[BADBEHAVIOR] detected IP ... ban for 86400s` after about ten. When every client arrives from one address, one client would ban all of them. That happens with loopback tests through `docker-proxy`, with rootless Docker, and behind a proxy without `USE_REAL_IP`; Docker's published ports otherwise keep the client address. Consider `BAD_BEHAVIOR_STATUS_CODES` without `401`, and preserve the real client address (`USE_REAL_IP` behind another proxy).
- **Headers.** The template loosens the default Content-Security-Policy so the web client can load its scripts, workers and media, and keeps cookies at `SameSite=Lax`. Check a custom CSP against the browser console.

## Verified live

Jellyfin 12.2.0 (`jellyfin/jellyfin:12.2.20261005-225228`), BunkerWeb 1.6.15, tested 2026-10-06 with a self-signed certificate (`GENERATE_SELF_SIGNED_SSL=yes`) and the template settings plus the two exclusions above.

| Flow                                                                                 | Detect | Block |
| ------------------------------------------------------------------------------------ | ------ | ----- |
| Setup wizard through `/Startup/*`, login (`Users/AuthenticateByName`), `System/Info` | pass   | pass  |
| Web client `/web/` and `config.json`                                                 | pass   | pass  |
| Library add and scan, playback info                                                  | pass   | pass  |
| 32 MB direct stream, ranged `206`, HLS `master.m3u8`                                 | pass   | pass  |
| Profile image upload, 21 MB body refused with `413`                                  | pass   | pass  |
| Websocket `/socket` upgrade and frames                                               | pass   | pass  |

Without the exclusions detect logged `930130` on `/web/config.json` and `920420` on the image upload. Block-mode boundary checks: a path traversal string in `/web/config.json?a=`, `config.json` or `web.config` under another path, an `image/svg+xml` body on the image path, an `image/png` body on another path, and SQL injection strings on the image path got `403`.

Not tested: the browser UI with JavaScript, transcoding under load, `/Items/<id>/Images/` uploads, subtitle upload, DLNA and SyncPlay, and Jellyfin's known-proxy setting.
