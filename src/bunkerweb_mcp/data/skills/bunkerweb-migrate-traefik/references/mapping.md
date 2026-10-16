# Mapping: Traefik to BunkerWeb

Verified at BunkerWeb v1.6.15 for every BunkerWeb name. Traefik label and middleware names are Traefik's: check them against the user's Traefik version (v2 and v3 differ, for example `ipwhitelist` and `ipallowlist`). Rows marked **run** were converted and probed against Traefik v3.7.13 ([verified-live.md](verified-live.md)); rows marked **not run** come from the setting definitions only.

## Label to label

With Docker autoconf, BunkerWeb reads labels from the application container. Each setting is `bunkerweb.<SETTING>=<value>`: the `bunkerweb.` prefix and the plain setting name, never `<site>_<SETTING>` and never `bunkerweb.io/` (that is the Kubernetes annotation form). A container becomes a service only if it carries `bunkerweb.SERVER_NAME`, and one container is one service. Tell the user to remove every `traefik.*` label from it, not only `traefik.enable`.

Custom configs use `bunkerweb.CUSTOM_CONF_<TYPE>_<NAME>` with `SERVER_HTTP`, `SERVER_STREAM`, `MODSEC`, `MODSEC_CRS`, `CRS_PLUGINS_BEFORE` or `CRS_PLUGINS_AFTER`. Global `http` and `default-server-http` configs cannot be a label: mount a file instead.

In a compose file every `$` in a label value is written `$$`, regex captures and `$is_args` included.

## Mapping

Traefik routers that share a host become one BunkerWeb service. A router that differs only by `PathPrefix` and middlewares needs no location of its own unless the upstream differs or the path is rewritten: the per-path settings below carry the path themselves.

| Traefik                                                                            | BunkerWeb label                                                                                                                                | Notes                                                                                                                                                                                                                                    |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `routers.<r>.rule=Host(`a.com`)` (**run**)                                         | `bunkerweb.SERVER_NAME=a.com`                                                                                                                  | `Host(a) \|\| Host(b)` becomes `a b`, space-separated (**not run**). `HostRegexp` has no equivalent: list the names.                                                                                                                     |
| `services.<s>.loadbalancer.server.port=2368` (**run**)                             | `bunkerweb.USE_REVERSE_PROXY=yes` and `bunkerweb.REVERSE_PROXY_HOST=http://<service>:2368`                                                     | A full URL with the compose service name, not just a port. The application must share a Docker network with BunkerWeb.                                                                                                                   |
| `PathPrefix(`/api`)` in the rule (**run**)                                         | numbered `bunkerweb.REVERSE_PROXY_URL_<n>=/api`, `bunkerweb.REVERSE_PROXY_HOST_<n>=...`                                                        | Set both of the pair. A prefix match, like Traefik's: `/api` also matches `/apix`. `PathRegexp` becomes a `~ regex` or `^...$` value. Each location reads its own `REVERSE_PROXY_HEADERS_<n>` and `REVERSE_PROXY_WS_<n>`.                |
| `routers.<r>.entrypoints=web,websecure` (**run**)                                  | published ports `80:8080`, `443:8443` on the BunkerWeb container                                                                               | Custom entrypoint ports: change the published port, not `HTTP_PORT` or `HTTPS_PORT`. A router bound to `web` only and one bound to `websecure` only become one service that answers on both ports.                                       |
| `tls.certresolver=<name>` (**not run**)                                            | `bunkerweb.AUTO_LETS_ENCRYPT=yes`, `bunkerweb.EMAIL_LETS_ENCRYPT=<mail>`                                                                       | The resolver's email lives in Traefik's static config. The run used `bunkerweb.GENERATE_SELF_SIGNED_SSL=yes` instead, which gave a working HTTPS port on a test host.                                                                    |
| `tls.certresolver` with `dnschallenge` (**not run**)                               | `bunkerweb.LETS_ENCRYPT_CHALLENGE=dns`, `bunkerweb.LETS_ENCRYPT_DNS_PROVIDER`, `bunkerweb.LETS_ENCRYPT_DNS_CREDENTIAL_ITEM`                    | Credentials are re-entered.                                                                                                                                                                                                              |
| middleware `redirectscheme.scheme=https` (**run**)                                 | `bunkerweb.REDIRECT_HTTP_TO_HTTPS=yes`                                                                                                         | The redirect `Location` has no port: BunkerWeb redirects to the default HTTPS port, so Traefik's `port` option has no counterpart. `AUTO_REDIRECT_HTTP_TO_HTTPS` already redirects once a certificate is configured.                     |
| middleware `redirectregex` (**run**)                                               | `bunkerweb.REDIRECT_FROM=/old`, `bunkerweb.REDIRECT_TO=https://example.org/new`                                                                | `REDIRECT_FROM` is an nginx `location` value, so a prefix: `/oldies` would redirect too where the Traefik regex `^https?://[^/]+/old$` would not (not probed). `permanent=true` is the default `301`; `REDIRECT_TO_STATUS_CODE`.         |
| middleware `basicauth.users` (**run**)                                             | `bunkerweb.USE_AUTH_BASIC=yes`, `bunkerweb.AUTH_BASIC_LOCATION=/secure`, `bunkerweb.AUTH_BASIC_USER`, `bunkerweb.AUTH_BASIC_PASSWORD`          | Traefik holds hashes; BunkerWeb takes plain-text passwords and hashes them itself, so users need new passwords. Without `AUTH_BASIC_LOCATION` the whole site is covered. More users: `AUTH_BASIC_USER_<n>`, `_PASSWORD_<n>`.             |
| middleware `ratelimit.average`, `.period`, `.burst` (**run**)                      | `bunkerweb.USE_LIMIT_REQ=yes`, `bunkerweb.LIMIT_REQ_URL_<n>=/login`, `bunkerweb.LIMIT_REQ_RATE_<n>=3r/m`                                       | Rate format `3r/m`. Use the numbered pair: the unnumbered `LIMIT_REQ_URL` and `LIMIT_REQ_RATE` are the default `/` rule at `2r/s`. Traefik's `burst` has no setting; see the traps in `SKILL.md`.                                        |
| middleware `ipallowlist.sourcerange`, whole site (v2: `ipwhitelist`) (**not run**) | `bunkerweb.USE_GREYLIST=yes`, `bunkerweb.GREYLIST_IP=<ranges>`                                                                                 | Site-wide: every other address is denied on every path. `WHITELIST_IP` does not restrict. The greylist only logs in detect mode.                                                                                                         |
| middleware `ipallowlist.sourcerange`, one path (**run**)                           | the two labels above plus `bunkerweb.GREYLIST_URI=^(?!/admin)`, or a location `REVERSE_PROXY_URL_<n>=/admin` with `REVERSE_PROXY_INCLUDES_<n>` | Either gave 200 for the allowed address and 403 otherwise. The include is a file in the BunkerWeb container holding `allow <ip>;` and `deny all;`, enforced in detect too. `USE_REAL_IP=yes` when the client IP is in `X-Forwarded-For`. |
| middleware `headers.stsseconds`, `.stsincludesubdomains` (**run**)                 | `bunkerweb.STRICT_TRANSPORT_SECURITY=max-age=<s>; includeSubDomains`                                                                           | Default is `max-age=63072000; includeSubDomains; preload`. Both proxies send it on HTTPS only.                                                                                                                                           |
| middleware `headers.customresponseheaders` (**run**)                               | `bunkerweb.CUSTOM_HEADER=Name: value`                                                                                                          | Service-wide, numbered for more (`CUSTOM_HEADER_2`). `REVERSE_PROXY_HEADERS_CLIENT` is per location. Headers BunkerWeb manages (CSP, frame, referrer) have their own setting.                                                            |
| middleware `headers.customrequestheaders` (**run**)                                | `bunkerweb.REVERSE_PROXY_HEADERS=Name value`                                                                                                   | Per location: repeat as `REVERSE_PROXY_HEADERS_<n>` on every location the Traefik middleware covered. An entry replaces BunkerWeb's default of the same name.                                                                            |
| middleware `stripprefix.prefixes` (**run**)                                        | `bunkerweb.REVERSE_PROXY_URL_<n>=^/api/(.*)$` and `bunkerweb.REVERSE_PROXY_HOST_<n>=http://<service>:8080/$1$is_args$args`                     | A regex location; the capture and the query string are written into the upstream. Do not use an include with `rewrite ... break` (skips BunkerWeb's Lua checks) or a host with a trailing path (sends everything to `/`).                |
| middleware `replacepathregex` (**not run**)                                        | the same regex location with the replacement in `REVERSE_PROXY_HOST_<n>`                                                                       | Untested beyond the `stripprefix` form.                                                                                                                                                                                                  |
| middleware `compress` (**run**)                                                    | `bunkerweb.USE_GZIP=yes`                                                                                                                       | A 3 KB response came back `gzip` on both. `bunkerweb.USE_BROTLI=yes` exists (**not run**); there is no zstd setting in core.                                                                                                             |
| middleware `forwardauth.address` (**not run**)                                     | `bunkerweb.REVERSE_PROXY_AUTH_REQUEST`, `bunkerweb.REVERSE_PROXY_AUTH_REQUEST_SIGNIN_URL`, `bunkerweb.REVERSE_PROXY_AUTH_REQUEST_SET`          | nginx `auth_request` semantics: the address is a subrequest location, not a Traefik URL. Test it.                                                                                                                                        |
| middleware `buffering.maxrequestbodybytes` (**run**)                               | `bunkerweb.MAX_CLIENT_SIZE=5m` (one path: `REVERSE_PROXY_MAX_CLIENT_SIZE_<n>`)                                                                 | 4 MiB passed and 6 MiB got `413` on both. Default is `10m`. `memrequestbodybytes` has no setting.                                                                                                                                        |
| websocket routes (automatic in Traefik) (**run**)                                  | `bunkerweb.REVERSE_PROXY_WS=yes`                                                                                                               | Traefik upgrades websockets without a flag; BunkerWeb needs it set, per location. In block mode CRS refused the echo server's `/.ws` path (rule `920440`).                                                                               |
| `retry`, `circuitbreaker`, `inflightreq`, `passtlsclientcert` (**not run**)        | none; list as not carried over                                                                                                                 | `USE_LIMIT_CONN` limits connections per IP, not in-flight requests per router. mTLS: `USE_MTLS` and its `MTLS_*` settings.                                                                                                               |
| `loadbalancer.server` with several replicas (**not run**)                          | none in core                                                                                                                                   | `REVERSE_PROXY_HOST` takes one target. Options: the BunkerWeb PRO Load Balancer plugin, or keep a balancer in front of replicas.                                                                                                         |

Resolve `@file` and `@docker` names first: a label router in the run used `secure-headers@file`, `size-limit@file` and `gz@file`, so its headers, body limit and compression came from `dynamic.yml` and had to be written as labels on the container.

## The stack autoconf needs

Name every container; a label set alone does nothing. Build it from [autoconf.md in the `bunkerweb` skill](https://github.com/bunkerity/bunkerweb-skills/blob/main/skills/bunkerweb/references/autoconf.md) or the [Docker autoconf docs](https://docs.bunkerweb.io/latest/integrations/#docker-autoconf), and pin every image to a tag. This stack was run end to end (the images below, project networks, ports on `127.0.0.1`), converted labels and all:

| Container      | Image                                  | Must have                                                                                                                |
| -------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `bunkerweb`    | `bunkerity/bunkerweb:1.6.15`           | label `bunkerweb.INSTANCE=yes`, env `AUTOCONF_MODE=yes`, `API_WHITELIST_IP`, `API_TOKEN`, ports `80:8080`, `443:8443`    |
| `bw-scheduler` | `bunkerity/bunkerweb-scheduler:1.6.15` | env `AUTOCONF_MODE=yes`, `MULTISITE=yes`, empty `SERVER_NAME` and `BUNKERWEB_INSTANCES`, `DATABASE_URI`, `SECURITY_MODE` |
| `bw-autoconf`  | `bunkerity/bunkerweb-autoconf:1.6.15`  | env `AUTOCONF_MODE=yes`, the same `DATABASE_URI`, `DOCKER_HOST` pointing at a socket proxy                               |
| socket proxy   | `tecnativa/docker-socket-proxy:v0.5.0` | the Docker socket mounted read-only, `CONTAINERS=1`; the docs use the `nightly` tag, pin the one you vet                 |
| database       | `mariadb:11`                           | a database and user matching `DATABASE_URI`; keep it off the network BunkerWeb itself uses                               |

Set `SECURITY_MODE=detect` on the scheduler as the default and flip one service at a time with the `bunkerweb.SECURITY_MODE=block` label. `API_WHITELIST_IP` holds the subnet of the network shared by the instance and the scheduler, and `API_TOKEN` is the same value on both. With another autoconf on the Docker host, add `bunkerweb.NAMESPACE=<name>` to the instance and the services and `NAMESPACES=<name>` to `bw-autoconf`.

The application containers join the services network (an external network the stack file creates) and carry the labels. One site from the run, a Traefik router set with an `ipAllowList` on `/admin`, a `basicAuth` on `/secure`, a `rateLimit` on `/login` and a `stripPrefix` on `/api`:

```yaml
echo-a:
  image: jmalloc/echo-server:v0.3.7
  networks:
    - bw-services
  labels:
    - "bunkerweb.SERVER_NAME=a.example.com"
    - "bunkerweb.SECURITY_MODE=detect"
    - "bunkerweb.USE_REVERSE_PROXY=yes"
    - "bunkerweb.REVERSE_PROXY_URL=/"
    - "bunkerweb.REVERSE_PROXY_HOST=http://echo-a:8080"
    - "bunkerweb.REVERSE_PROXY_WS=yes"
    - "bunkerweb.REVERSE_PROXY_HEADERS=X-Custom-Req traefik-req"
    - "bunkerweb.REVERSE_PROXY_URL_2=^/api/(.*)$$"
    - "bunkerweb.REVERSE_PROXY_HOST_2=http://echo-a:8080/$$1$$is_args$$args"
    - "bunkerweb.REVERSE_PROXY_HEADERS_2=X-Custom-Req traefik-req"
    - "bunkerweb.GENERATE_SELF_SIGNED_SSL=yes"
    - "bunkerweb.REDIRECT_HTTP_TO_HTTPS=yes"
    - "bunkerweb.STRICT_TRANSPORT_SECURITY=max-age=31536000; includeSubDomains"
    - "bunkerweb.CUSTOM_HEADER=X-Custom-Resp: traefik-resp"
    - "bunkerweb.MAX_CLIENT_SIZE=5m"
    - "bunkerweb.USE_GZIP=yes"
    - "bunkerweb.REDIRECT_FROM=/old"
    - "bunkerweb.REDIRECT_TO=https://example.org/new"
    - "bunkerweb.USE_REAL_IP=yes"
    - "bunkerweb.USE_GREYLIST=yes"
    - "bunkerweb.GREYLIST_IP=10.1.2.3"
    - "bunkerweb.GREYLIST_URI=^(?!/admin)"
    - "bunkerweb.LIMIT_REQ_URL_2=/login"
    - "bunkerweb.LIMIT_REQ_RATE_2=3r/m"
    - "bunkerweb.USE_AUTH_BASIC=yes"
    - "bunkerweb.AUTH_BASIC_LOCATION=/secure"
    - "bunkerweb.AUTH_BASIC_USER=alice"
    - "bunkerweb.AUTH_BASIC_PASSWORD=<new password>"
```

`GENERATE_SELF_SIGNED_SSL` is for a test host only; use `AUTO_LETS_ENCRYPT` or `USE_CUSTOM_SSL` in production. `REAL_IP_FROM` defaults to the three private ranges, which covered the Docker gateway in the run.
