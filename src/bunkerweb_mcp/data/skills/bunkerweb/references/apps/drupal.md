# Drupal behind BunkerWeb

Template: https://github.com/bunkerity/bunkerweb-templates/tree/main/templates/drupal (read at hub commit 4ba433a, 2026-09-19). It sets TLS, the reverse proxy, a rate limit, caching and the CRS plugin `drupal-rule-exclusions`, and nothing else. Run against a live 1.6.15 stack it needed four additions.

## What Drupal needs

- **Rate limit.** The template's `LIMIT_REQ_RATE=2r/s` on `/` is far below a Drupal admin page. In block mode the installer got `429` at its fourth step and everything after it failed. Use `50r/s`; the template's `LIMIT_REQ_URL_1=/core/install.php` at `5r/s` is fine at human pace, but a script clicking through the installer exceeds it.
- **Body size.** The template sets no `MAX_CLIENT_SIZE`, so the default `10m` answers `413` to a 21 MB image, in detect mode too. Set `MAX_CLIENT_SIZE=100m` (and raise PHP's `upload_max_filesize` and `post_max_size`, which default to 2M).
- **Methods.** The default `ALLOWED_METHODS` at v1.6.15 is `GET|POST|HEAD|QUERY`. JSON:API `PATCH` and `DELETE` get `405` in block mode only (detect lets them through). Set `GET|POST|HEAD|OPTIONS|PATCH|DELETE`. This value drops the default `QUERY`; no flow here used it, and `|QUERY` at the end keeps it.
- **JSON:API content type.** `Content-Type: application/vnd.api+json` hits CRS rule 920420 (`403`). Custom config type `modsec-crs`, name `drupal-jsonapi-content-type`: append `|application/vnd.api+json|` to `tx.allowed_request_content_type` (copy the CRS default list, then add) and add the companion rule that arms the JSON body parser for it. Without the companion the body parses to nothing and the SQL injection, XSS and command rules stop inspecting JSON:API bodies. See [bunkerweb-modsecurity-crs-tuning](../../../bunkerweb-modsecurity-crs-tuning/SKILL.md). The list change applies to every request.
- **File upload through JSON:API.** `POST /jsonapi/<entity>/<bundle>[/<uuid>]/field_*` sends `application/octet-stream`, also rule 920420. Type `modsec-crs`, name `drupal-jsonapi-file-upload`: `ctl:ruleRemoveTargetById=920420;REQUEST_HEADERS:Content-Type` chained to `REQUEST_FILENAME "@rx ^/jsonapi/[a-z0-9_]+/[a-z0-9_]+/(?:[0-9a-f-]{36}/)?field_[a-z0-9_]+$"` and `REQUEST_METHOD "@streq POST"`, with `t:normalizePath`.
- **Drupal side.** JSON:API is read-only until Settings, Web services, JSON:API is set to accept writes. The `standard` profile of 11.4 has no Article type (apply `core/recipes/article_content_type`). The container sees `Host` without the port.

## Verified live

Drupal 11.4.8 (`drupal:11.4.8-apache`, PHP 8.5), PostgreSQL 17.11, BunkerWeb 1.6.15, CRS 4.29.0, plugin `drupal-rule-exclusions` 1.0.0, 2026-10-06.

| Flow                                                     | Detect                     | Block, template       | Block, tuned |
| -------------------------------------------------------- | -------------------------- | --------------------- | ------------ |
| Web install (4 form steps and the batch)                 | pass, install limit logged | `429`, install stalls | pass         |
| Login, 9 admin pages, enable modules, cron, public pages | pass, 2r/s limit logged    | fail after the stall  | pass         |
| JSON:API read with Basic auth                            | pass                       | fail after the stall  | pass         |
| JSON:API create (`vnd.api+json`)                         | pass, 920420 logged        | `403`                 | pass         |
| JSON:API `PATCH`, `DELETE`                               | pass                       | `405`                 | pass         |
| 21 MB image: JSON:API raw upload, node form multipart    | `413`                      | `413`                 | pass         |

Boundary checks on the tuned stack, all `403` with rule ids in the log: a SQL injection string inside a `vnd.api+json` body, on `/jsonapi/node/article` and on `/jsonapi/node/page`; an unlisted type (`application/x-evil`, `image/png`) on the same path and on `/user/login`; `octet-stream` on the collection path, on `...field_image.bak`, with `PATCH`, on `/user/login`, on `/node/add/article`, on `/jsonapi/node/article/<uuid>`, and with a SQL injection string in the query of the upload path. A `sqlmap/1.7` agent gets `403`.

## Not tested

Drupal's own modules from the network, `trusted_host_patterns` and `reverse_proxy` settings, multilingual and large installs, Let's Encrypt, the template's `drupal-rule-exclusions` effect (no admin form tripped a rule, so it is neither confirmed nor shown to be needed).
