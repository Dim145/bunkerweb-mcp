# Verified live

Run on 2026-10-06 with `owasp/modsecurity-crs:4.30.0-nginx-202610051210` (nginx 1.30.5, ModSecurity 3) and `owasp/modsecurity-crs:4.30.0-apache-202610051210` (httpd 2.4.69, ModSecurity 2), each in front of `jmalloc/echo-server:v0.3.7`, against BunkerWeb 1.6.15 (CRS 4.29.0) in front of the same echo server. Both images ran the same settings: paranoia level 2 for blocking and 3 for detection, anomaly thresholds 10 inbound and 10 outbound, methods `GET POST HEAD OPTIONS`, one extra allowed content type, body limits of 5 MiB, `SecRuleEngine On`, and the two CRS exclusion files (one custom deny rule, one custom score rule, one `@ipMatch` rule on `/admin`, one `ctl:` on a phase 1 rule, one `ctl:` on a phase 2 rule and argument, `SecRuleRemoveById`, `SecRuleUpdateTargetById`). The BunkerWeb services were converted from those files as this skill describes: the paranoia levels, thresholds and content type as `SecAction` lines in `modsec-crs`, the first file in `modsec-crs`, the second in `modsec`, and the container variables as BunkerWeb settings. `USE_BAD_BEHAVIOR`, `USE_DNSBL` and `USE_BUNKERNET` were turned off so the replay compared ModSecurity only; the rest of BunkerWeb's defaults stayed on.

The same 31 requests went to every target, paced a second apart, once in detect and once in block, over HTTP and over HTTPS on BunkerWeb. Each row below is the status and the rule ids that the container log named for that request (ids only; counts when a request matched more than four). Rule ids come from the source container's JSON audit log or `ModSecurity: Warning` lines, and from `[id "..."]` in BunkerWeb's container log. BunkerWeb answered the same status and the same ids over HTTPS as over HTTP on all 31 requests, in both modes and for both conversions.

## Result

- Against the nginx image, 27 of 31 requests gave the same status and the same ids in block mode. The four others are explained below: real IP (2), allowed methods (1) and the unknown host (1). In detect mode every request the image blocked answered 200 and logged the same ids, apart from the rows explained below.
- Against the Apache image, 25 of 31 gave the same status and ids in block mode once the log-only line `980170` (ModSecurity 2 only) is ignored. The six others are engine differences, the websocket, methods and the unknown host.
- Each conversion mattered: the same requests against BunkerWeb with nothing converted, and with everything converted except the exclusions, differ from the image where the table in the last section says they do.

## nginx image against BunkerWeb

| Request                                                | nginx image                      | BunkerWeb detect                 | BunkerWeb block                  |
| ------------------------------------------------------ | -------------------------------- | -------------------------------- | -------------------------------- |
| `GET /?q=hello`                                        | 200                              | 200                              | 200                              |
| SQL injection, several rules (`q`)                     | 403, 11 ids                      | 200, 11 ids                      | 403, 11 ids                      |
| XSS `<script>` (`q`)                                   | 403, 8 ids                       | 200, 8 ids                       | 403, 8 ids                       |
| path traversal (`f`)                                   | 403, 7 ids                       | 200, 7 ids                       | 403, 7 ids                       |
| `/?r=1'` (one rule, score 5)                           | 200, 942330                      | 200, 942330                      | 200, 942330                      |
| `/?comment=1'` (`SecRuleUpdateTargetById`)             | 200                              | 200                              | 200                              |
| `/?other=1'`                                           | 200, 942330                      | 200, 942330                      | 200, 942330                      |
| `/search?q=1'` (`ctl:ruleRemoveTargetById`)            | 200                              | 200                              | 200                              |
| `/find?q=1'`                                           | 200, 942330                      | 200, 942330                      | 200, 942330                      |
| no `Accept` header (`SecRuleRemoveById 920300`)        | 200                              | 200                              | 200                              |
| no `User-Agent` header                                 | 200, 920320                      | 200, 920320                      | 200, 920320                      |
| `%01` plus `r=1'` (paranoia level 2 rules)             | 403, 920271 920272 942330 949110 | 200, 920271 920272 942330 949110 | 403, 920271 920272 942330 949110 |
| `%e2%82%ac` (paranoia level 3 rule only)               | 200, 920272                      | 200, 920272                      | 200, 920272                      |
| `/?promo=BLOCKME` (custom score rule)                  | 200, 1000300                     | 200, 1000300                     | 200, 1000300                     |
| `promo=BLOCKME` plus `r=1'`                            | 403, 1000300 942330 949110       | 200, 1000300 942330 949110       | 403, 1000300 942330 949110       |
| `X-Debug: on` (custom deny rule)                       | 403, 1000200                     | 200, 1000200                     | 403, 1000200                     |
| `/admin`, client at the Docker gateway                 | 200                              | 200                              | 200                              |
| `/admin`, `X-Forwarded-For: 10.1.2.3`                  | 200                              | 200                              | 200                              |
| `/admin`, `X-Forwarded-For: 203.0.113.9`               | 200                              | 200, 1000210                     | 403, 1000210                     |
| `/admin/x`, `X-Forwarded-For: 203.0.113.9`             | 200                              | 200, 1000210                     | 403, 1000210                     |
| `/administrator`, `X-Forwarded-For: 203.0.113.9`       | 200                              | 200                              | 200                              |
| `OPTIONS /`                                            | 200                              | 200                              | 200                              |
| `PUT /`                                                | 200, 911100                      | 200                              | 405                              |
| `POST` `application/octet-stream`, 100 B               | 200                              | 200                              | 200                              |
| `POST` urlencoded, 150 kB (limit raised from 131072)   | 200                              | 200                              | 200                              |
| multipart upload, 4 MiB                                | 200, 920272                      | 200, 920272                      | 200, 920272                      |
| multipart upload, 6 MiB                                | 403                              | 200                              | 403                              |
| echoed `X-Leak` header, SQL error text in the response | 200, 951230                      | 200, 951230                      | 200, 951230                      |
| websocket handshake on `/.ws`, one echoed frame        | 101                              | 101                              | 101                              |
| unknown `Host`                                         | 200                              | 403                              | 403                              |
| `POST` `text/plain`, 10 B                              | 200, 920420                      | 200, 920420                      | 200, 920420                      |

- `/admin` with `X-Forwarded-For: 203.0.113.9`: the image answered 200 and logged no rule: its `REAL_IP_HEADER` and `SET_REAL_IP_FROM` sit in the `location /` include, and its `@ipMatch` rule did not refuse the forwarded address, which is outside the allowed ranges. BunkerWeb with `USE_REAL_IP=yes` matched rule `1000210` on `203.0.113.9` and block mode answered 403. The Apache image behaves like BunkerWeb here (403, `1000210`).
- `PUT /`: the image allowed it (CRS rule `911100` logged, score 5 below the threshold of 10). BunkerWeb refused it with 405 from its own `ALLOWED_METHODS` check (`GET|POST|HEAD|OPTIONS`), before ModSecurity; in detect mode it only logged. Add `PUT` to `ALLOWED_METHODS` if the source allowed it.
- unknown `Host`: the image's default server answered 200. With `DISABLE_DEFAULT_SERVER=yes` BunkerWeb answered 403.
- The 6 MiB multipart upload: 403 in the image and in block mode, 200 in detect mode (`SecRuleEngine DetectionOnly` refuses nothing). It is the converted `MODSECURITY_SEC_REQUEST_BODY_LIMIT=5242880` that does it; with nothing converted BunkerWeb let it through (see the last table).
- `920272` is a paranoia level 3 rule: the nginx image and BunkerWeb both logged it, on `%e2%82%ac` and on the 4 MiB multipart upload, once `tx.detection_paranoia_level=3` was set, and both answered 200. With nothing converted (level 1) BunkerWeb logged no level 2 or level 3 id.

## Apache image against BunkerWeb

| Request                                                | Apache image                      | BunkerWeb detect                 | BunkerWeb block                  |
| ------------------------------------------------------ | --------------------------------- | -------------------------------- | -------------------------------- |
| `GET /?q=hello`                                        | 200                               | 200                              | 200                              |
| SQL injection, several rules (`q`)                     | 403, 14 ids                       | 200, 11 ids                      | 403, 11 ids                      |
| XSS `<script>` (`q`)                                   | 403, 9 ids                        | 200, 8 ids                       | 403, 8 ids                       |
| path traversal (`f`)                                   | 403, 8 ids                        | 200, 7 ids                       | 403, 7 ids                       |
| `/?r=1'` (one rule, score 5)                           | 200, 942330 980170                | 200, 942330                      | 200, 942330                      |
| `/?comment=1'` (`SecRuleUpdateTargetById`)             | 200                               | 200                              | 200                              |
| `/?other=1'`                                           | 200, 942330 980170                | 200, 942330                      | 200, 942330                      |
| `/search?q=1'` (`ctl:ruleRemoveTargetById`)            | 200                               | 200                              | 200                              |
| `/find?q=1'`                                           | 200, 942330 980170                | 200, 942330                      | 200, 942330                      |
| no `Accept` header (`SecRuleRemoveById 920300`)        | 200                               | 200                              | 200                              |
| no `User-Agent` header                                 | 200, 920320 980170                | 200, 920320                      | 200, 920320                      |
| `%01` plus `r=1'` (paranoia level 2 rules)             | 403, 5 ids                        | 200, 920271 920272 942330 949110 | 403, 920271 920272 942330 949110 |
| `%e2%82%ac` (paranoia level 3 rule only)               | 200, 920272 980170                | 200, 920272                      | 200, 920272                      |
| `/?promo=BLOCKME` (custom score rule)                  | 200, 1000300 980170               | 200, 1000300                     | 200, 1000300                     |
| `promo=BLOCKME` plus `r=1'`                            | 403, 1000300 942330 949110 980170 | 200, 1000300 942330 949110       | 403, 1000300 942330 949110       |
| `X-Debug: on` (custom deny rule)                       | 403, 1000200                      | 200, 1000200                     | 403, 1000200                     |
| `/admin`, client at the Docker gateway                 | 200                               | 200                              | 200                              |
| `/admin`, `X-Forwarded-For: 10.1.2.3`                  | 200                               | 200                              | 200                              |
| `/admin`, `X-Forwarded-For: 203.0.113.9`               | 403, 1000210                      | 200, 1000210                     | 403, 1000210                     |
| `/admin/x`, `X-Forwarded-For: 203.0.113.9`             | 403, 1000210                      | 200, 1000210                     | 403, 1000210                     |
| `/administrator`, `X-Forwarded-For: 203.0.113.9`       | 200                               | 200                              | 200                              |
| `OPTIONS /`                                            | 200                               | 200                              | 200                              |
| `PUT /`                                                | 200, 911100 980170                | 200                              | 405                              |
| `POST` `application/octet-stream`, 100 B               | 200                               | 200                              | 200                              |
| `POST` urlencoded, 150 kB (limit raised from 131072)   | 200                               | 200                              | 200                              |
| multipart upload, 4 MiB                                | 200                               | 200, 920272                      | 200, 920272                      |
| multipart upload, 6 MiB                                | 413                               | 200                              | 403                              |
| echoed `X-Leak` header, SQL error text in the response | 200, 951230 980170                | 200, 951230                      | 200, 951230                      |
| websocket handshake on `/.ws`, one echoed frame        | 200                               | 101                              | 101                              |
| unknown `Host`                                         | 200                               | 403                              | 403                              |
| `POST` `text/plain`, 10 B                              | 200, 920420 980170                | 200, 920420                      | 200, 920420                      |

- `980170` is a correlation summary that ModSecurity 2 writes for every scored request. ModSecurity 3 (the nginx image, BunkerWeb) never writes it.
- The SQL injection request: ModSecurity 2 also matched `932236` and `932238`; ModSecurity 3 did not, in the nginx image or in BunkerWeb. Same CRS 4.30.0 files in both images, so this is the engine. Both blocked.
- The 4 MiB multipart upload: ModSecurity 3 logged `920272` for the binary part, ModSecurity 2 did not. Both answered 200.
- The 6 MiB multipart upload: ModSecurity 2 answered 413 (`Request body (Content-Length) is larger than the configured limit`), ModSecurity 3 answers 403.
- The websocket: the Apache image set up `BACKEND_WS` but has no `proxy_wstunnel` module (`httpd -M` lists `proxy_module` and `proxy_http_module` only), so the upgrade request was served as a plain `GET` and answered 200 with no frame. BunkerWeb answered 101 and echoed the frame with `REVERSE_PROXY_WS_2=yes`.
- `PUT` and the unknown host: as for the nginx image.
- Speed: ModSecurity 2 in this image took 3.6 s for a 100 kB urlencoded body of random words, 18 s for 256 kB, and did not answer a 1 MiB body in 25 s. The nginx image took 1.2 s for the same 1 MiB body and 4.6 s for 4 MiB. `curl` against the Apache image with a 4 MiB `a=AAAA...` body timed out at 70 s and the error log held `PCRE limits exceeded (-47)` for rules `932250` and `932260`. BunkerWeb answered a 4 MiB urlencoded body of `A` characters with 200 in its first pass of the run.

## What each conversion changed

The same requests against BunkerWeb with nothing converted (defaults only) and against BunkerWeb with everything converted except the four exclusions (`ctl` on `/.ws`, `ctl` on `/search`, `SecRuleRemoveById 920300`, `SecRuleUpdateTargetById 942330`):

| Request                                                | nginx image                      | BunkerWeb, nothing converted, detect | nothing converted, block | converted without the exclusions, block |
| ------------------------------------------------------ | -------------------------------- | ------------------------------------ | ------------------------ | --------------------------------------- |
| `/?r=1'` (one rule, score 5)                           | 200, 942330                      | 200                                  | 200                      | 200, 942330                             |
| `/?comment=1'` (`SecRuleUpdateTargetById`)             | 200                              | 200                                  | 200                      | 200, 942330                             |
| `/search?q=1'` (`ctl:ruleRemoveTargetById`)            | 200                              | 200                                  | 200                      | 200, 942330                             |
| no `Accept` header (`SecRuleRemoveById 920300`)        | 200                              | 200                                  | 200                      | 200, 920300                             |
| `%01` plus `r=1'` (paranoia level 2 rules)             | 403, 920271 920272 942330 949110 | 200                                  | 200                      | 403, 920271 920272 942330 949110        |
| `/?promo=BLOCKME` (custom score rule)                  | 200, 1000300                     | 200                                  | 200                      | 200, 1000300                            |
| `promo=BLOCKME` plus `r=1'`                            | 403, 1000300 942330 949110       | 200                                  | 200                      | 403, 1000300 942330 949110              |
| `X-Debug: on` (custom deny rule)                       | 403, 1000200                     | 200                                  | 200                      | 403, 1000200                            |
| `/admin`, `X-Forwarded-For: 203.0.113.9`               | 200                              | 200                                  | 200                      | 403, 1000210                            |
| `OPTIONS /`                                            | 200                              | 200, 949110                          | 405                      | 200                                     |
| `PUT /`                                                | 200, 911100                      | 200, 949110                          | 405                      | 405                                     |
| `POST` `application/octet-stream`, 100 B               | 200                              | 200, 920420 949110                   | 403, 920420 949110       | 200                                     |
| `POST` urlencoded, 150 kB (limit raised from 131072)   | 200                              | 200, 200002                          | 400, 200002              | 200                                     |
| multipart upload, 6 MiB                                | 403                              | 200                                  | 200                      | 403                                     |
| echoed `X-Leak` header, SQL error text in the response | 200, 951230                      | 200, 951230 959100                   | response cut mid-body    | 200, 951230                             |
| websocket handshake on `/.ws`, one echoed frame        | 101                              | 101, 920440 949110                   | 403, 920440 949110       | 101, 920440                             |
| unknown `Host`                                         | 200                              | 403                                  | 403                      | 403                                     |
| `POST` `text/plain`, 10 B                              | 200, 920420                      | 200, 920420 949110                   | 403, 920420 949110       | 200, 920420                             |

- Nothing converted, paranoia level 1 and threshold 5: no level 2 or level 3 id at all, no custom rule, a `text/plain` or `application/octet-stream` body refused through `920420`, a 150 kB urlencoded body refused with 400 by `200002` (the default `MODSECURITY_REQ_BODY_NO_FILES_LIMIT` is 131072), the 6 MiB upload let through (BunkerWeb derives the limit from `MAX_CLIENT_SIZE`, `10m`), `OPTIONS` and `PUT` answered 405 by `ALLOWED_METHODS`, the websocket refused by `920440`, and the response with SQL error text cut off by outbound rule `959100` (the outbound threshold defaults to 4).
- In detect mode with nothing converted, `OPTIONS` and `PUT` still logged `949110`: BunkerWeb forces `911100` to `allow,nolog`, but `allow` is not applied under `DetectionOnly`, so its score of 5 reached the default threshold of 5.
- Converted without the exclusions: `942330` fires for `comment` and for `/search?q=`, `920300` fires with no `Accept` header, and `920440` fires on `/.ws`. The websocket still answered 101 only because one score of 5 is below the converted threshold of 10; at the default threshold it is refused (previous row).

## Placement and reload checks

Run on throwaway BunkerWeb stacks of the same release, block mode.

| Check                                                                                                       | Result                                                                                                          |
| ----------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `ctl:ruleRemoveById=920440` (phase 1 target) in `modsec`                                                    | `920440` still logged on the websocket handshake; in `modsec-crs` it was not.                                   |
| `ctl:ruleRemoveTargetById=942330;ARGS:q` (phase 2 target) in `modsec`                                       | no `942330` for `/search?q=1'`. Same from `modsec-crs`.                                                         |
| `SecRuleRemoveById 920300`, `SecRuleUpdateTargetById 942330 "!ARGS:comment"` in `modsec-crs` or in `modsec` | both worked from either.                                                                                        |
| The same two directives in the file that loads before the CRS on the Apache image (ModSecurity 2)           | neither worked: `920300` and `942330` on `comment` were still logged.                                           |
| A chained rule whose last link has no action list, followed by a comment line                               | reload refused: `Rules error ... Expecting an action, got: # next`. With `"t:none"` on the last link it loaded. |
| `SecServerSignature "x"` in `modsec`                                                                        | reload refused: `SecServerSignature is not supported`.                                                          |
| `SecRule` id used twice, or id `200002` (BunkerWeb's own) reused                                            | reload refused: `Rule id: ... is duplicated`.                                                                   |
| `SecAction` with id `900200` added to `modsec-crs`                                                          | reload succeeded, no message.                                                                                   |

A refused reload is logged by the scheduler as `Error while reloading bunkerweb, failing over to last working configuration`: BunkerWeb keeps serving the previous configuration and no change reaches any service until the file is fixed. In the nginx CRS image's own engine, `SecCacheTransformations`, `SecGuardianLog`, `SecRequestBodyInMemoryLimit`, `SecContentInjection` and `SecPdfProtect` were also refused at `nginx -t`, while `SecDisableBackendCompression`, `SecUploadKeepFiles` and `SecAuditLogDirMode` were accepted (checked in that image, not on BunkerWeb).

## Inventory commands

These ran as written against the two running images (`docker exec <container> sh -c '...'`):

- `nginx -T | grep -nE 'modsecurity(_rules_file)? '` gives `modsecurity on;` and the rules file path. `httpd -M | grep security2` and `httpd -t -D DUMP_INCLUDES | grep -iE 'modsec'` list the module and every included rule file in load order.
- `grep -nE '^[[:space:]]*Include' <rules file>` lists the includes of the file the engine loads.
- The CRS release is in `grep -m1 -oE "ver:'OWASP_CRS/[0-9.]+" <rules dir>/REQUEST-901-INITIALIZATION.conf` (it printed `4.30.0` in both images). A looser `grep -o 'OWASP_CRS/[0-9.]*'` printed `3.1.0` from an old comment line: do not use it.
- `grep -vE '^[[:space:]]*(#|$)' <crs-setup.conf> | grep -E 'id:|setvar'` prints the values the operator or the image's entrypoint activated.
- `docker inspect <container> --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'` shows which rule files are yours.

## Not exercised

HSTS, redirects and rate limits (the images have `NGINX_ALWAYS_TLS_REDIRECT`, `APACHE_ALWAYS_TLS_REDIRECT` and `HSTS_MAX_AGE`; they belong to the nginx and Apache migration skills), the audit log settings, CRS plugins, CRS 3, a package install of ModSecurity (not a container), and the environment-variable and autoconf-label forms of a custom config in this run.
