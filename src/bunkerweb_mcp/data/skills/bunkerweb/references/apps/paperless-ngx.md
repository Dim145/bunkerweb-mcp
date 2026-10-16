# Paperless-ngx behind BunkerWeb

No template exists in the template hub for this app. Everything below was found by running it live against BunkerWeb 1.6.15, see `## Verified live`.

- **Upstream and URL.** `REVERSE_PROXY_HOST` points at the container's port `8000`. The test set `PAPERLESS_URL` to the public address with scheme and port; it was not run without it.
- **WebSocket.** The upload progress bar listens on `/ws/status/` (Django Channels). `REVERSE_PROXY_WS` defaults to `no`, and with it the handshake got a plain `200` page instead of `101`. Set it to `yes`; documents still imported without it, but the status stream never starts.
- **Method allow-list.** The API edits objects with `PATCH`, `PUT` and `DELETE`. The default `ALLOWED_METHODS` (`GET|POST|HEAD|QUERY`) answered `405` to all three. Set `GET|POST|HEAD|OPTIONS|PUT|PATCH|DELETE` (`OPTIONS` was not exercised). This value drops the default `QUERY`; no flow here used it, and `|QUERY` at the end keeps it.
- **Upload size.** `MAX_CLIENT_SIZE` defaults to `10m`; a 22 MB PDF to `/api/documents/post_document/` got `413`. The test used `100m`; set it above your largest scan.
- **Rate limit and bans.** `LIMIT_REQ_RATE` defaults to `2r/s` per URL and answered `429` to the web login `POST`; the test used `20r/s`. `BAD_BEHAVIOR_STATUS_CODES` counts `401`, `403`, `404` and `429` by default, ten in 60 seconds bans the client IP for a day (`bwcli unban <ip>`).
- **API version.** The test client sent `Accept: application/json; version=9`; the proxy passes it unchanged.

## CRS exclusions

One flow fired a CRS rule. The `match` field of a tag, correspondent, document type or storage path holds a regular expression that the user types, and a quantifier such as `\d{4,}` reads as a shell brace expansion: rule `932280` scores it (`ARGS:json.match`, JSON body) and the request is blocked. Everything else passed with no exclusion: 22 MB upload, consume and download, workflow templates with Jinja text, saved views, custom field queries, full text search, mail account and rule forms.

Custom config of type `modsec` (environment form `<server_name>_CUSTOM_CONF_MODSEC_paperless`; in a Compose `environment:` block write each `$` as `$$`):

```text
SecRule REQUEST_FILENAME "@rx ^/api/(?:tags|correspondents|document_types|storage_paths)(?:/[0-9]+)?/?$" \
    "id:10000300,phase:1,pass,nolog,t:none,t:normalizePath,chain,ctl:ruleRemoveTargetById=932280;ARGS:json.match"
SecRule REQUEST_METHOD "@rx ^(?:POST|PUT|PATCH)$" "t:none,nolog"
```

The target is the literal name `json.match`: a regex target (`ARGS:/re/`) loads without error and does nothing at 1.6.15. The exclusion removes only rule `932280` and only for that field on those four routes. The same field on `mail_rules`, and the field `json.name` on the tag route, still got `403`; a SQL injection or a shell command in `json.match` got `403` (`942100`, `942190`, `942270`; `930120`, `932160`); a `GET` with the regex in the query string got `403`.

## Verified live

Paperless-ngx 3.3.0 (`paperlessngx/paperless-ngx:3.3.0`, PostgreSQL 17, Redis 8), BunkerWeb 1.6.15, tested 2026-10-06 with a self-signed certificate (`GENERATE_SELF_SIGNED_SSL=yes`) and the settings and exclusion above.

| Flow                                                                        | Block, defaults | Block, settings only                  | Block, final    |
| --------------------------------------------------------------------------- | --------------- | ------------------------------------- | --------------- |
| Login page, static files, web login, dashboard                              | login `429`     | pass                                  | pass            |
| API token, CRUD of tags, correspondents, types, custom fields, saved views  | pass            | pass                                  | pass            |
| Regex in a tag `match`, Jinja storage path, workflow template, mail account | not run         | tag with a regex `403`, the rest pass | pass            |
| 22 MB PDF upload, consume, download (sha256 equal), preview, thumbnail      | `413`           | pass                                  | pass            |
| `PATCH`, bulk edit, `DELETE`                                                | `405`           | pass                                  | pass            |
| `/ws/status/` during a consume                                              | no upgrade      | pass (8 frames)                       | pass (8 frames) |
| Unauthenticated API call `401`                                              | not run         | pass                                  | pass            |

In detect mode with default settings the 22 MB upload got `413`, the `/ws/status/` request got `200` instead of `101`, and `DELETE` scored `949110` (method); no CRS rule scored a benign request except `932280`.

Boundary checks in block mode, each with the rule id in the log, are in the paragraph above; a scanner User-Agent got `403` and a plain request `200`. The final run had no denied request.

Not tested: mail fetching against a real mail server, the consume folder and webhooks, OIDC and social login, the barcode and AI features, document sharing links, and more than one worker.
