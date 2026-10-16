# Verified live

HAProxy 3.4.6 and BunkerWeb 1.6.15, 2026-10-06, both in front of the same echo server, one request set. The ACL is real-IP based (HAProxy took the address from `X-Forwarded-For` when the connection came from a private range, BunkerWeb through `USE_REAL_IP`), so the test sends `X-Forwarded-For: 10.1.2.3` (allowed) and `203.0.113.9` (denied).

| Request                                                       | HAProxy                          | BunkerWeb detect                             | BunkerWeb block         |
| ------------------------------------------------------------- | -------------------------------- | -------------------------------------------- | ----------------------- |
| `GET /`                                                       | 200                              | 200                                          | 200                     |
| websocket handshake on `/.ws`, then one echoed text frame     | 101                              | 101                                          | 101 \*                  |
| 4 MiB multipart upload / 6 MiB multipart upload               | 200 / 413                        | 200 / 413                                    | 200 / 413               |
| `/admin` allowed address / denied address / `/admin/x`        | 200 / 403 / 403                  | 200 / 403 / 403                              | 200 / 403 / 403         |
| `/administrator`, denied address                              | 200                              | 200                                          | 200                     |
| `/old`                                                        | 301 to `https://example.org/new` | same                                         | same                    |
| HSTS header on HTTP / on HTTPS                                | present / not tested             | absent / present                             | absent / present        |
| unknown `Host`                                                | 421 (explicit rule)              | 403 (`DISABLE_DEFAULT_SERVER=yes`)           | 403                     |
| 4 MiB `application/x-www-form-urlencoded` body                | 200                              | 200                                          | 200 \*\* (limit raised) |
| 100 B `application/octet-stream` body                         | 200                              | 200                                          | 403 \*\*\*              |
| six `GET /login` with no pause (limit 3, rule on `/login`)    | 200 x3, then 429 x3              | 200 x6                                       | 200 x3, then 429 x3     |
| websocket idle 9 s, read timeout `5s` / `1h` on that location | not run                          | closed after 5 s / still open, echo received | not run                 |

The rows that differ:

- \* The block run needed a scoped exclusion. CRS rule `920440` ("URL file extension is restricted") fires on the path `/.ws` and the handshake got 403. That path is the echo server's own; a path like `/socket` does not trip it. The fix that worked was a service-scoped `modsec-crs` config (scheduler environment variable `<server_name>_CUSTOM_CONF_MODSEC_CRS_<name>`) with `ctl:ruleRemoveById=920440`, matched on that exact path. Use [`bunkerweb-modsecurity-crs-tuning`](https://github.com/bunkerity/bunkerweb-skills/tree/main/skills/bunkerweb-modsecurity-crs-tuning) to write it.
- \*\* With the default `MODSECURITY_REQ_BODY_NO_FILES_LIMIT` (131072 bytes) the same body got 400 in block mode (rule `200002`); detect mode only logged it. The live service raised it to `5242880`. File uploads (multipart) are not counted against it.
- \*\*\* CRS rule `920420` rejects content types outside its allowed list, `application/octet-stream` included. HAProxy passes anything. See [`bunkerweb-modsecurity-crs-tuning`](https://github.com/bunkerity/bunkerweb-skills/tree/main/skills/bunkerweb-modsecurity-crs-tuning) for the policy variable that widens the list.
- Rate limit: detect mode refuses nothing. The log shows `detected client IP ... limit for URL /login (current rate = 4r/m and max rate = 3r/m)`. Block mode refused from the fourth request on, as HAProxy did. The windows are not the same: HAProxy counted over 10 seconds, BunkerWeb over a minute (`3r/m`), so pick the BunkerWeb rate from the traffic, not by arithmetic on the old number.
- HSTS: `http-response set-header` also answers on plain HTTP; BunkerWeb sends it only on HTTPS (`src/common/core/headers/headers.lua`, the `ssl` check at line 95).
- The default `2r/s` rule applies to every path of every service, with no stick-table behind it in the old config. See the traps.
