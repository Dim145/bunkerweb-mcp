# Vaultwarden behind BunkerWeb

No template exists in the template hub for this app. Everything below was found by running it live against BunkerWeb 1.6.15, see `## Verified live`.

When you answer a migration, the answer must carry: the settings below, each with its symptom and status code; the CRS rule ids and the exclusion; and the detect-first advice below as the answer's detect run, in its four ordered steps with its reason. Read every bullet before you write.

- **WebSockets.** Sync notifications use one WebSocket on the main port, `/notifications/hub`. Set `REVERSE_PROXY_WS=yes` once, on the `/` proxy entry, and point `REVERSE_PROXY_HOST` at the container's port `80`. That entry carries the socket: there is no second port, and no second `REVERSE_PROXY_URL` entry for `/notifications/hub` (an nginx `location` for the hub does not need a BunkerWeb counterpart; the live run used one entry).
- **Method allow-list.** Keep `GET`, `POST` and `HEAD`, and add `PUT` and `DELETE`: set `ALLOWED_METHODS=GET|POST|HEAD|OPTIONS|PUT|DELETE`. Say in the answer: the default `GET|POST|HEAD|QUERY` has neither `PUT` nor `DELETE`, so in block mode the web vault's item and folder edits (`PUT`) and deletions (`DELETE`) fail with `405` (a folder `PUT` got it). `OPTIONS` was not exercised. This value drops the default `QUERY`; no flow here used it, and `|QUERY` at the end keeps it.
- **Upload size.** `MAX_CLIENT_SIZE` defaults to `10m`. A 25 MB attachment got `413` and the nginx error `client intended to send too large body`. The test used `100m`.
- **Import size.** `MODSECURITY_REQ_BODY_NO_FILES_LIMIT` defaults to `131072`. A JSON import of 300 items (354 KB) was refused with `400` and rule `200002`, `Request body excluding files is bigger than the maximum expected`. The test used `5m`.
- **Rate limit.** `LIMIT_REQ_RATE` defaults to `2r/s` per URL. A script creating about 8 items per second got `429`. Loading the web vault's static files (19 files in 0.4 s) was not limited. Raise it only if your clients script bulk writes; the test used `20r/s`.
- **Start in detect mode, because a false positive bans the user.** Write this as the detect run of the answer, as four ordered steps, and give the reason: (1) set `SECURITY_MODE=detect` first; (2) use the web vault and the browser extension while you read the BunkerWeb log; (3) write the exclusion below for what the log shows; (4) only then switch to `block`. The reason, stated in the answer: in block mode every false positive is a `403`, and repeated `403` answers count toward the bad-behavior ban. The default `BAD_BEHAVIOR_STATUS_CODES` is `400 401 403 404 405 429 444`, so `403` and `429` count; about ten of them within 60 seconds ban the client IP for 86400 s, one day (`bwcli unban <ip>` lifts it). A burst of bulk writes that hits the `429` rate limit counts the same way.
- **Certificate.** Name the certificate source in the settings of the answer. A nginx block that reads Let's Encrypt files keeps them with `USE_CUSTOM_SSL=yes`, `CUSTOM_SSL_CERT` and `CUSTOM_SSL_KEY` set to the `fullchain.pem` and `privkey.pem` paths, mounted into the scheduler (it reads them, not the BunkerWeb container). The alternative is `AUTO_LETS_ENCRYPT=yes`, where BunkerWeb issues its own certificate and port 80 must reach it.
- **Redirect.** Plain HTTP answers `301` to `https://<host>/` without the port, so a test on a non-standard HTTPS port needs the HTTPS URL used directly.

## CRS exclusions

Every vault field arrives as an EncString: base64 pieces joined by `|`. CRS reads random ones as shell, file or script payloads. Without exclusions 9 of 500 and 11 of 500 item saves got `403`. Rules seen: `930120`, `932125`, `932370`, `932380`, `941120` on fields of the JSON body such as `ARGS:json.name` (item create and import bodies; this is the target the log shows, not a pattern to write into the exclusion), and `920120` on `FILES:data` (the attachment filename is an EncString too).

Limit the exclusion to the item API paths (`/api/ciphers`, plus `/api/folders` and `/api/sends`) and to the methods `POST` and `PUT`; the attachment rule is `POST` only. Never lift these rules for every path or method. Custom config of type `modsec`, per service (environment form `<server_name>_CUSTOM_CONF_MODSEC_vaultwarden`):

```text
SecRule REQUEST_FILENAME "@rx ^/api/(?:ciphers|folders|sends)(?:/|$)" \
    "id:10000100,phase:1,pass,nolog,t:none,t:normalizePath,chain,\
    ctl:ruleRemoveTargetById=930120;ARGS,ctl:ruleRemoveTargetById=932125;ARGS,\
    ctl:ruleRemoveTargetById=932370;ARGS,ctl:ruleRemoveTargetById=932380;ARGS,\
    ctl:ruleRemoveTargetById=941120;ARGS"
SecRule REQUEST_METHOD "@rx ^(?:POST|PUT)$" "t:none,nolog"
SecRule REQUEST_FILENAME "@rx ^/api/ciphers/[0-9a-f-]{36}/attachment/[0-9a-f]+$" \
    "id:10000101,phase:1,pass,nolog,t:none,t:normalizePath,chain,ctl:ruleRemoveTargetById=920120;FILES:data"
SecRule REQUEST_METHOD "@streq POST" "t:none,nolog"
```

Under the code, state the scope in the answer as one line: type `modsec`; paths `/api/ciphers`, `/api/folders` and `/api/sends`; methods `POST` and `PUT` (the attachment rule `POST` only); `ctl:ruleRemoveTargetById` for the named rule ids; the CRS stays on and rule `949110` is never excluded.

The path also lists folders and sends because they carry EncStrings too; no hit was seen there and it was not stress-tested. In a Compose `environment:` block write each `$` as `$$`. The exclusion removes the whole `ARGS` collection for those five rules, because a regex target and the `ARGS_POST` collection had no effect in 1.6.15 (a probe rule inside the BunkerWeb container still denied) and are unverified on other releases. In the answer, name only the working targets, `ARGS` or a literal name such as `ARGS:json.name`, and do not write a regex target or `ARGS_POST`. A literal list is impractical because of the array indices (`json.login.uris.array_0.uri`). The cost: those five rules no longer inspect query-string or form arguments on those paths and methods. Header and cookie checks stay, and so does every other rule.

## Verified live

Vaultwarden 1.37.4 (`vaultwarden/server:1.37.4`, SQLite), BunkerWeb 1.6.15, tested 2026-10-06 with a self-signed certificate (`GENERATE_SELF_SIGNED_SSL=yes`), the settings and the exclusion above. The flows are scripted: the master key and every EncString are built the way the web vault builds them.

| Flow                                                | Detect (defaults) | Block, no fix | Block, final |
| --------------------------------------------------- | ----------------- | ------------- | ------------ |
| Web vault page, assets, `/api/config`               | pass              | pass          | pass         |
| Register, prelogin, password login, refresh token   | pass              | pass          | pass         |
| Profile, sync, folder create and `PUT`              | pass              | pass          | pass         |
| 30 item creates, `PUT`, `GET`, `DELETE`             | pass              | `403` once    | pass         |
| Import of 300 items (354 KB)                        | pass              | `400`         | pass         |
| 25 MB attachment upload and download, sha256 equal  | `413`             | `403`         | pass         |
| WebSocket hub and the push after an item update     | pass              | pass          | pass         |
| `/admin` login, user list, config save, diagnostics | pass              | pass          | pass         |

Boundary checks in block mode cover the five `ARGS` rules (`930120`, `932125`, `932370`, `932380`, `941120`), with one real EncString per rule: in the excluded body it got `200`; the same string in a cookie (sent on a `GET` under `/api/ciphers/`), in a JSON field on `/identity/accounts/prelogin`, and in a query argument of a `GET` under `/api/ciphers/` each got `403` with that rule id logged. The `920120` attachment exclusion has no boundary pair: it was only seen through the real upload, which passed with the exclusion and got `403` without it. A SQL injection string in the excluded field got `403` (`942100`, `942190`, `942270`). A scanner User-Agent got `403` and a plain request `200`. After the exclusion 1,200 item creates (about 8,400 EncStrings) were all `200`.

Not tested: public Send access (the app itself answered `404` for the routes tried), SSO, two-factor, mail, the mobile and browser-extension clients, organizations and collections, icon downloads (no outbound access), and the `OPTIONS` method.
