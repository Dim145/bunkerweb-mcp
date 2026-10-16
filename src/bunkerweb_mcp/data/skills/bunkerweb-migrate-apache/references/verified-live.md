# Verified live

Apache httpd 2.4.69 and BunkerWeb 1.6.15, 2026-10-06, both in front of the same echo server, one request set. The ACL is real-IP based (`X-Forwarded-For` trusted from private ranges on both sides), so the test sends `X-Forwarded-For: 10.1.2.3` (allowed) and `203.0.113.9` (denied).

| Request                                                   | Apache                           | BunkerWeb detect | BunkerWeb block       |
| --------------------------------------------------------- | -------------------------------- | ---------------- | --------------------- |
| `GET /`                                                   | 200                              | 200              | 200                   |
| websocket handshake on `/.ws`, then one echoed text frame | 101                              | 101              | 101 \*                |
| 4 MiB multipart upload / 6 MiB multipart upload           | 200 / 413                        | 200 / 413        | 200 / 413             |
| `/admin` allowed address / denied address / `/admin/x`    | 200 / 403 / 403                  | 200 / 403 / 403  | 200 / 403 / 403       |
| `/administrator`, denied address                          | 200                              | 200              | 200                   |
| `/old`                                                    | 301 to `https://example.org/new` | same             | same                  |
| HSTS header on HTTP / on HTTPS                            | present / not tested             | absent / present | absent / present      |
| 4 MiB `application/x-www-form-urlencoded` body            | 200                              | 200              | 400 \*\*              |
| 100 B `application/octet-stream` body                     | 200                              | 200              | 403 \*\*\*            |
| six `GET /login` with no pause                            | 200 x6                           | 200 x6           | 200, 200, then 429 x4 |

The rows that differ:

- \* The block run needed a scoped exclusion. CRS rule `920440` ("URL file extension is restricted") fires on the path `/.ws` and the handshake got 403. That path is the echo server's own; a path like `/socket` does not trip it. The fix that worked was a service-scoped `modsec-crs` config (scheduler environment variable `<server_name>_CUSTOM_CONF_MODSEC_CRS_<name>`) with `ctl:ruleRemoveById=920440`, matched on that exact path. Use [`bunkerweb-modsecurity-crs-tuning`](https://github.com/bunkerity/bunkerweb-skills/tree/main/skills/bunkerweb-modsecurity-crs-tuning) to write it.
- \*\* ModSecurity rule `200002` ("Request body excluding files is bigger than the maximum expected"): non-file bodies above `MODSECURITY_REQ_BODY_NO_FILES_LIMIT` (default 131072 bytes) get 400 in block mode and only a log line in detect. Raising it to `5242880` on the second service let the same body through. File uploads (multipart) are not counted against it.
- \*\*\* CRS rule `920420` rejects content types outside its allowed list, `application/octet-stream` included. Apache passes anything. See [`bunkerweb-modsecurity-crs-tuning`](https://github.com/bunkerity/bunkerweb-skills/tree/main/skills/bunkerweb-modsecurity-crs-tuning) for the policy variable that widens the list.
- Burst: BunkerWeb enables `USE_LIMIT_REQ` at `2r/s` for every client IP. In detect mode the log shows `detected client IP ... limit for URL ...` and nothing is refused. A test script or a monitor that sends several requests a second gets 429 after cutover.
- HSTS: `Header always set` also answers on plain HTTP; BunkerWeb sends it only on HTTPS (`src/common/core/headers/headers.lua`, the `ssl` check at line 95).
