# WordPress behind BunkerWeb

Template: https://github.com/bunkerity/bunkerweb-templates/tree/main/templates/wordpress (read at hub commit 4ba433a, 2026-09-19). Its settings were applied unchanged to a live 1.6.15 stack and then tuned. Three changes were forced.

## What WordPress needs

- **Methods.** The template allows `GET|POST|HEAD|OPTIONS`. In block mode `PUT` and `DELETE` get `405`. Set `ALLOWED_METHODS` to `GET|POST|HEAD|OPTIONS|PUT|DELETE` for REST clients that use them. That value drops the default `QUERY`; no flow here used it, and `|QUERY` at the end keeps it. The block editor needs nothing: it sends `POST` with `X-HTTP-Method-Override`, and CRS did not flag it.
- **Rate limit.** `LIMIT_REQ_RATE=5r/s` on `/` is below what one browser needs for one wp-admin page. 80 asset requests over 8 connections drew 60 `429` answers (detect mode only logs them). In block mode the `429`s count as bad behavior and the client IP was **banned for 24 hours** after that one burst. Raise the rate (`50r/s` passed) and throttle the login on its own: `LIMIT_REQ_URL_1=/wp-login.php`, `LIMIT_REQ_RATE_1=2r/s`.
- **CRS plugin.** Keep `MODSECURITY_CRS_PLUGINS=wordpress-rule-exclusions`. The scheduler downloads it from the plugin registry, so it needs outbound HTTPS.
- **Uploads.** `MAX_CLIENT_SIZE=50m` passed 21 MB by multipart and by raw `application/octet-stream`. The PHP limits (`upload_max_filesize`, `post_max_size`) are WordPress's own and default to 2M.
- **Permalinks.** Without pretty permalinks `/wp-json/` is an Apache `404`, not a BunkerWeb one. This image needed two saves before `.htaccess` held the rewrite rules.
- **Port.** WordPress sees `Host` without the port. Test on 443, or redirects lose the port.

## Exclusions added

The classic uploader hits CRS rule 932180 for any file name containing `class` (`classic.zip`, `classroom.pdf`): `class` is in CRS's restricted-upload word list. Custom config type `modsec`, name `wordpress-upload-filename`:

```text
SecRule REQUEST_FILENAME "@rx ^/wp-admin/async-upload\.php$" "id:10000010,phase:1,pass,nolog,t:none,t:normalizePath,chain,ctl:ruleRemoveTargetById=932180;FILES:async-upload"
SecRule REQUEST_METHOD "@streq POST" "t:none,nolog"
```

Tradeoff: that one field no longer meets the word list, so a `.htaccess` file name passes rule 932180 there; WordPress's own type check still applies.

A raw REST upload that sends the file's own type (`Content-Type: image/png`) hits rule 920420. Type `modsec-crs` (a phase 1 rule), name `wordpress-media-content-type`, id `10000020`: the same chain shape with `REQUEST_FILENAME "@rx ^/wp-json/wp/v2/media$"` and `ctl:ruleRemoveTargetById=920420;REQUEST_HEADERS:Content-Type`. Every content type is then accepted on that endpoint and the body is not inspected as a form. Skip it when clients use multipart, as the block editor does.

## Verified live

WordPress 7.1.2, MariaDB 11.8.9, BunkerWeb 1.6.15 (Docker), CRS 4.29.0, 2026-10-06. Runs: detect and block with the template as shipped, then block tuned.

| Flow                                                        | Detect               | Block, template    | Block, tuned |
| ----------------------------------------------------------- | -------------------- | ------------------ | ------------ |
| Install, login, 10 wp-admin pages, permalinks, public pages | pass                 | pass               | pass         |
| REST read, create post, update by method override           | pass                 | pass               | pass         |
| REST `PUT` and `DELETE`                                     | pass                 | `405`              | pass         |
| 21 MB media upload, multipart and raw octet-stream          | pass                 | pass               | pass         |
| Raw `image/png` media upload                                | pass, 920420 logged  | `403`              | pass         |
| Classic uploader, 21 MB, file `classic.zip`                 | pass, 932180 logged  | `403`              | pass         |
| Settings save, heartbeat, XML-RPC, wp-cron                  | pass                 | pass               | pass         |
| 80 asset requests, 8 connections                            | pass, 60 limit lines | `429`, then banned | pass         |

Boundary checks on the tuned stack, all `403` with the matching rule id in the log: the uploader path with another field name (`async-upload2`, `file`); field `async-upload` on `admin-ajax.php`, on `/wp-json/wp/v2/media`, on `async-upload.php.bak` and through `/wp-admin/../wp-json/...`; `image/png` on `/wp-json/wp/v2/posts`, `admin-ajax.php`, `/wp-json/wp/v2/media/1` and with `PUT`. A SQL injection string on the excluded media path is still `403`. A `sqlmap/1.7` agent gets `403` (913100, 949110).

## Not tested

Plugin and theme installs, multisite, WooCommerce, Let's Encrypt, the crawler whitelist (it needs reverse DNS), and the template's `admin-ajax` exclusions for 941130, 942200, 942440 and 942450: none fired in these flows, so they are neither confirmed nor shown to be needed.
