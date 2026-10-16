# Immich behind BunkerWeb

No template exists in [the template hub](https://github.com/bunkerity/bunkerweb-templates) for Immich (the hub has no Immich template at commit `4ba433a`, 2026-09-19), so everything below comes from a live run against BunkerWeb 1.6.15, see `## Verified live`.

- **Methods.** Immich's API uses `PUT`, `PATCH` and `DELETE`. BunkerWeb's default `ALLOWED_METHODS` is `GET|POST|HEAD|QUERY`, so in block mode profile edits, album renames and asset deletion answer `405` (log: `[ACCESS] denied access from misc : method PUT is not allowed`). Set `ALLOWED_METHODS` to `GET|POST|HEAD|OPTIONS|PUT|DELETE|PATCH`. This value drops the default `QUERY`; no flow here used it, and `|QUERY` at the end keeps it. In detect mode the same requests pass but each logs rule `949110` at score 5 with no contributing rule line, which is the signature of this problem.
- **Rate limit, the one that bites.** `LIMIT_REQ_RATE` defaults to `2r/s`. A gallery loads many thumbnails at once: 40 parallel thumbnail requests got 2 times `200` and 38 times `429`. With `LIMIT_REQ_RATE=100r/s`, 40 and 80 parallel requests all returned `200`; 150 returned 102 `200` and 48 `429`. Pick a rate for your peak.
- **`429` leads to a ban.** `429` is in the default `BAD_BEHAVIOR_STATUS_CODES`, so a burst of rate-limited requests fills the counter and BunkerWeb bans the client IP (`[ACCESS] IP ... is banned with reason bad behavior`, default 86400 s). When every client arrives from one address, one noisy client locks everyone out. That happens with loopback tests through `docker-proxy`, with rootless Docker, and behind a proxy without `USE_REAL_IP`; Docker's published ports otherwise keep the client address. Raise the rate first, and keep `429` and `404` out of `BAD_BEHAVIOR_STATUS_CODES` if mobile apps probe.
- **WebSocket.** The web app connects to `/api/socket.io/` with the websocket transport; Immich answers `400` to the polling transport itself. `REVERSE_PROXY_WS=yes` on the `/` location was enough: the upgrade returned `101` and the server sent its `0{"sid":...}` frame.
- **Uploads.** `MAX_CLIENT_SIZE` must be above your largest video; the test used `50g`. A 32 MB multipart `POST /api/assets` and a download of it (sha256 matched) went through, and `206` ranged playback worked. BunkerWeb logs `a client request body is buffered to a temporary file` for big uploads, which is only a warning.
- **CRS.** No exclusion was needed: the photo and video multipart uploads, the JSON bodies (search, albums, shared links) and the socket.io handshake raised no ModSecurity rule other than the method score above.
- **Immich side.** The server listens on `2283`, so `REVERSE_PROXY_HOST` is `http://immich-server:2283`. Immich's own trusted-proxy option was not tested.

## Verified live

Immich v3.2.4 (`ghcr.io/immich-app/immich-server`), the PostgreSQL image with VectorChord and Valkey 9 from Immich's v3.2.4 compose file, BunkerWeb 1.6.15, tested 2026-10-06 with a self-signed certificate (`GENERATE_SELF_SIGNED_SSL=yes`). The machine-learning container was left out.

| Flow                                                                        | Detect                     | Block                                      |
| --------------------------------------------------------------------------- | -------------------------- | ------------------------------------------ |
| Admin sign-up, login, `users/me`, server info                               | pass                       | pass                                       |
| Web app pages `/` and `/auth/login`                                         | pass                       | pass                                       |
| Photo and 32 MB video upload, original download, thumbnail, ranged playback | pass                       | pass                                       |
| Search, albums (create, rename), shared link and public page                | pass                       | pass                                       |
| `PUT`, `PATCH`, `DELETE` calls                                              | pass (with `949110` score) | pass with `ALLOWED_METHODS`, `405` without |
| Websocket `/api/socket.io/` upgrade                                         | pass                       | pass                                       |

Block-mode smoke check: a scanner User-Agent, a SQL injection string and a path traversal string each got `403`, and `TRACE` got `405`.

Not tested: smart search and face recognition (no machine-learning container), the mobile app, the browser UI with JavaScript, and Immich's trusted-proxy setting.
