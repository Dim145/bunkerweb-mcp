# authentik behind BunkerWeb

No template-hub entry exists for authentik. Every setting below was tested live on BunkerWeb 1.6.15; see [Verified live](#verified-live).

When you answer a migration, name each of these settings in the answer, with its reason: the `REVERSE_PROXY_WS` rule for `/ws/`, `REVERSE_PROXY_INTERCEPT_ERRORS=no`, `ALLOWED_METHODS` with `PUT`, `PATCH`, `DELETE` and `OPTIONS`, `MAX_CLIENT_SIZE=64m` (with the `413` explanation) and the CRS exclusions. Read every bullet below before you write.

- **Upstream.** Proxy to the server container on `http://<server>:9000`. Leave `REVERSE_PROXY_URL=/` for the site.
- **Error bodies.** Set `REVERSE_PROXY_INTERCEPT_ERRORS=no`. With the default (`yes`) BunkerWeb replaces the body of every status in `INTERCEPTED_ERROR_CODES` (`400`, `401`, `403`, `404` and more) with its own HTML page. Observed on `400` and `403`: the OAuth `invalid_grant` reply and API errors reached the client as HTML. Always list this setting in the answer.
- **WebSockets.** `/ws/client/` (the admin UI) and `/ws/outpost/<id>/` (outposts) need `REVERSE_PROXY_WS=yes`, default `no`; without it the upgrade is ignored and the endpoint answers `200`. Add a second rule so only `/ws/` gets it: `REVERSE_PROXY_URL_1=/ws/`, the same `REVERSE_PROXY_HOST_1`, `REVERSE_PROXY_WS_1=yes`.
- **Methods.** The API saves with `PATCH` and `PUT`, deletes with `DELETE`, and answers CORS preflights with `OPTIONS`. Set `ALLOWED_METHODS=GET|POST|HEAD|OPTIONS|PUT|PATCH|DELETE`, or every one answers `405`. Always list this setting in the answer, with that reason. This value drops the default `QUERY`; no flow here used it, and `|QUERY` at the end keeps it.
- **Rate limit.** The default `LIMIT_REQ_RATE=2r/s` limits the login page and its static files; a burst of 24 static requests gave 16 `429`. `50r/s` passed the same burst.
- **Upload size.** Carry the source's `client_max_body_size 64m` over: set `MAX_CLIENT_SIZE=64m` for the service, or use the path-only rule below. Say in the answer that the default `10m` refuses file uploads larger than 10 MiB with `413`, even in detect mode. `POST /api/v3/admin/file/` takes uploads. Raise its limit for that path only: `REVERSE_PROXY_URL_2=/api/v3/admin/file/`, the same host, `REVERSE_PROXY_MAX_CLIENT_SIZE_2=64m`. A 21 MiB upload to another path still gets `413`. ModSecurity's body limit did not interfere at that size.
- **Bad behavior.** `429`, `403`, `401`, `400` and `404` from authentik itself count toward `BAD_BEHAVIOR_THRESHOLD` (10 per 60 s, 24 h ban). A script that makes ten failing API calls in a minute bans its own IP.
- **CRS exclusions** (`modsec` config type, service scope). authentik admins post Python, HTML and CSS as JSON, which the CRS reads as attacks. One chained rule per endpoint (anchored path with an optional UUID, method `POST|PUT|PATCH`) removes only the matching targets:
  - `/api/v3/policies/expression/`, target `ARGS:json.expression`: rules 932140, 933160, 934100, 941390, 942100, 942190.
  - `/api/v3/core/brands/`, target `ARGS:json.branding_custom_css`: rules 941100, 941130, 941160, 941170.
  - `/api/v3/stages/prompt/prompts/`, targets `ARGS:json.placeholder` (941100, 941120, 941160, 941390) and `ARGS:json.sub_text` (941160). Write the rules as in [bunkerweb-modsecurity-crs-tuning](../../../bunkerweb-modsecurity-crs-tuning/SKILL.md), one `ctl:ruleRemoveTargetById=<id>;<target>` per pair.
- **authentik side.** File uploads fail with a `500` ("No file management backend configured") until the server and worker mount a volume at `/data`. Pass `AUTHENTIK_BOOTSTRAP_PASSWORD` and `AUTHENTIK_BOOTSTRAP_TOKEN` on first start to script the first run.

## Verified live

authentik 2026.8.3 (`ghcr.io/goauthentik/server`), PostgreSQL 16.15, BunkerWeb 1.6.15, 2026-10-06. Self-signed certificate (`GENERATE_SELF_SIGNED_SSL=yes`), `SERVER_NAME=authentik.example.com`.

| Flow                                                                                                   | Detect                                            | Block                                            |
| ------------------------------------------------------------------------------------------------------ | ------------------------------------------------- | ------------------------------------------------ |
| Login through the flow executor, session cookie, `users/me`                                            | pass                                              | pass                                             |
| API calls with a bearer token                                                                          | pass                                              | pass                                             |
| `PATCH`, `PUT`, `DELETE`, `OPTIONS`                                                                    | pass (not logged)                                 | `405` until `ALLOWED_METHODS` is set, then pass  |
| Create a Python policy, a brand with CSS, a prompt with HTML                                           | pass, CRS hits logged                             | `403` until the exclusions, then pass            |
| 21 MiB upload to `/api/v3/admin/file/`                                                                 | `413`                                             | `413` until the path rule, then pass             |
| WebSockets `/ws/client/` and `/ws/outpost/<id>/`                                                       | `200` (no upgrade)                                | `101` after the `/ws/` rule                      |
| OIDC: discovery, JWKS, authorization code, token, userinfo, refresh, introspection, client credentials | pass                                              | pass                                             |
| OAuth error reply is JSON                                                                              | HTML                                              | JSON after `REVERSE_PROXY_INTERCEPT_ERRORS=no`   |
| Login flow at default `2r/s`                                                                           | pass, logged as `detected deny access from limit` | `429`, then a 24 h ban, until the rate is raised |

Boundary checks: each exclusion was tried with the payload on another target of the same path and on the same target of another path. All returned `403` with rule `949110`.

Detect mode logs rate-limit decisions as `[ACCESS] detected deny access from limit` but writes nothing for the method check, so `405` first shows up after the switch to block.

Not tested: SAML, LDAP and proxy outposts, the Kubernetes and multi-instance setups, a real browser (all flows were scripted), and `X-Forwarded-For` trust inside authentik.
