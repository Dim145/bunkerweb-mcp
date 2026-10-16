# BunkerWeb on Docker

Verified at v1.6.15. Source: `docs/integrations.md` (Docker), `docs/quickstart-guide.md`, `misc/integrations/docker.yml`, plus a live run of the compose file below on 2026-10-05.

The stack is two BunkerWeb containers plus your app:

- `bunkerweb` runs nginx, ModSecurity and the Lua plugins. It serves traffic and exposes an internal API on port 5000.
- `bw-scheduler` is the control plane. It holds every setting, generates the configuration, pushes it to `bunkerweb` and reloads it.
- Your app joins the `bw-services` network and is never published on a host port.

Add `bunkerity/bunkerweb-ui:1.6.15` and a real database when you want the web UI. If you want to configure through container labels instead of environment variables, use [autoconf.md](autoconf.md).

## Prerequisites

- Docker Engine and Compose v2.
- For Let's Encrypt: a public DNS record for the domain pointing at this host, and ports 80 and 443 reachable from the Internet (the default challenge is HTTP-01 on port 80).
- Free host ports 80 and 443. The compose file reads `BW_HTTP_PORT` and `BW_HTTPS_PORT` so you can move them for a test.
- A secret for the instance API. Generate it once and keep it in the shell or in a `.env` file next to the compose file.

## Compose file

Replace `app.example.com`, the e-mail address and the `myapp` service. Keep both BunkerWeb tags identical.

```yaml
# Instance API: admit the scheduler's network and require the same token on both sides.
x-bw-env: &bw-env
  API_WHITELIST_IP: "127.0.0.0/8 198.51.100.0/24"
  API_TOKEN: "${BW_API_TOKEN:?set BW_API_TOKEN before docker compose up}"

services:
  bunkerweb:
    image: bunkerity/bunkerweb:1.6.15
    ports:
      - "${BW_HTTP_PORT:-80}:8080/tcp"
      - "${BW_HTTPS_PORT:-443}:8443/tcp"
      - "${BW_HTTPS_PORT:-443}:8443/udp" # QUIC
    environment:
      <<: *bw-env # only API_* settings belong on this container
    restart: unless-stopped
    networks:
      - bw-universe
      - bw-services

  bw-scheduler:
    image: bunkerity/bunkerweb-scheduler:1.6.15
    depends_on:
      - bunkerweb
    environment:
      <<: *bw-env
      BUNKERWEB_INSTANCES: "bunkerweb" # service name of the instance above
      MULTISITE: "yes"
      SERVER_NAME: "app.example.com"
      DISABLE_DEFAULT_SERVER: "yes"
      SECURITY_MODE: "detect" # switch to "block" after reading the logs
      AUTO_LETS_ENCRYPT: "${BW_AUTO_LETS_ENCRYPT:-yes}"
      EMAIL_LETS_ENCRYPT: "you@yourdomain.tld"
      app.example.com_USE_REVERSE_PROXY: "yes"
      app.example.com_REVERSE_PROXY_URL: "/"
      app.example.com_REVERSE_PROXY_HOST: "http://myapp:8080"
    volumes:
      - bw-storage:/data # SQLite database, cache and backups
    restart: unless-stopped
    networks:
      - bw-universe

  myapp: # stand-in for your service: any image that listens on 8080
    image: bunkerity/bunkerweb-hello:v1.0
    restart: unless-stopped
    networks:
      - bw-services

volumes:
  bw-storage:

networks:
  bw-universe:
    ipam:
      config:
        - subnet: 198.51.100.0/24 # example range, use an unused subnet; keep in sync with API_WHITELIST_IP
  bw-services:
```

Why it looks like this:

- Every service setting is on `bw-scheduler`. Only the `API_*` settings are mirrored on `bunkerweb`, because the instance reads those itself.
- The instance API listens on every interface of `bw-universe`. `API_WHITELIST_IP` defaults to `127.0.0.0/8`, which does not admit the scheduler, so the compose file names the network's subnet. An empty `API_TOKEN` means no authentication at all for callers inside that subnet, so set the same non-empty value on both containers.
- With `MULTISITE: "yes"` a per-service setting is `<server_name>_<SETTING>`. A setting without a prefix is a default for every service. Leave `MULTISITE` unset for a single service and drop the prefixes.
- `DISABLE_DEFAULT_SERVER: "yes"` stops BunkerWeb answering requests for a host it does not serve.
- No network carries a `name:`, so Compose scopes both to the project. Add `external: true` and a `name:` to `bw-services` only when apps in other compose projects must join it.

Start it:

```bash
export BW_API_TOKEN="$(openssl rand -hex 24)"
docker compose up -d
```

## Per-service settings

Add more hostnames to `SERVER_NAME` (space-separated) and give each its own prefixed settings:

```yaml
services:
  bw-scheduler:
    environment:
      SERVER_NAME: "app.example.com api.example.com"
      app.example.com_USE_ANTIBOT: "captcha"
      api.example.com_USE_REVERSE_PROXY: "yes"
      api.example.com_REVERSE_PROXY_HOST: "http://api:3000"
```

Settings with context `global` (for example `API_WHITELIST_IP`, `MULTISITE`) cannot take a prefix. `src/common/settings.json` and each `src/common/core/<plugin>/plugin.json` state the context of every setting.

## Apply a change

Edit the `bw-scheduler` environment, then recreate only that container:

```bash
docker compose up -d bw-scheduler
```

The scheduler regenerates the configuration, pushes it to `bunkerweb` and reloads nginx without dropping connections. Wait for the log line before testing:

```bash
docker compose logs bw-scheduler 2>&1 | grep 'Successfully reloaded bunkerweb'
```

Observed: about 20 seconds from `up -d` to that line. A change to `API_WHITELIST_IP`, `API_TOKEN` or the port mappings is on the `bunkerweb` container too, so recreate both: `docker compose up -d bunkerweb bw-scheduler`.

## Upgrade

Full procedure: [docs/upgrading.md at v1.6.15](https://github.com/bunkerity/bunkerweb/blob/v1.6.15/docs/upgrading.md). There is no downgrade migration, so take a backup first. The backup directory must already exist inside the container:

```bash
docker compose exec -T bw-scheduler mkdir -p /tmp/bw-backup
docker compose exec -T -e BACKUP_DIRECTORY=/tmp/bw-backup bw-scheduler bwcli plugin backup save
docker compose cp bw-scheduler:/tmp/bw-backup ./bw-backup
```

Then change the tag on every BunkerWeb image (`bunkerweb`, `bw-scheduler`, and `bw-ui` or `bw-autoconf` if present) to the same new version and run:

```bash
docker compose pull
docker compose up -d
docker compose logs bw-scheduler
```

Read the scheduler log for migration errors. Confirm the running version with `docker compose exec -T bw-scheduler cat /usr/share/bunkerweb/VERSION`.

## Verify

The commands run against the local port without public DNS, so they set `BW_AUTO_LETS_ENCRYPT=no` and, when 80 and 443 are taken, `BW_HTTP_PORT` and `BW_HTTPS_PORT`. With Let's Encrypt on, plain HTTP answers `301` to HTTPS. For the real domain replace `http://127.0.0.1:${BW_HTTP_PORT:-80}` with `https://app.example.com` and drop the `Host` header.

Run every command in this section in the shell that ran the `export` below: they read `BW_API_TOKEN` from it, and a new shell has none. Start the stack in `detect` mode and wait for the first configuration to load (about 20 to 60 seconds):

```bash
export BW_API_TOKEN="$(openssl rand -hex 24)" BW_AUTO_LETS_ENCRYPT=no BW_HTTP_PORT=18080 BW_HTTPS_PORT=18443
docker compose up -d
timeout 180 bash -c 'until docker compose logs bw-scheduler 2>&1 | grep -q "Successfully reloaded bunkerweb"; do sleep 3; done'
docker compose ps
```

Expected: `bunkerweb` `Up ... (healthy)` and `bw-scheduler` `Up` (its healthcheck can still read `health: starting` for a few seconds after the first reload).

Check 1, the site is served through BunkerWeb:

```bash
curl -sS -i -H 'Host: app.example.com' "http://127.0.0.1:${BW_HTTP_PORT:-80}/" | grep -iE '^(HTTP/|server:|x-content-type-options:)'
```

Expected, exactly two lines: `HTTP/1.1 200 OK` and `X-Content-Type-Options: nosniff`, with no `Server:` line. BunkerWeb adds `X-Content-Type-Options` and strips the upstream's `Server` header by default (`REMOVE_HEADERS`). The upstream on its own answers with `Server: nginx/...` and no `X-Content-Type-Options`, so those two differences show that BunkerWeb is in the path.

Check 2, a benign scanner User-Agent. In `detect` mode it passes and the log shows what `block` would have stopped:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: app.example.com' -A 'sqlmap/1.7' "http://127.0.0.1:${BW_HTTP_PORT:-80}/"
docker compose logs bunkerweb 2>&1 | grep -oE 'id "(913100|949110)"' | sort -u
```

Expected in `detect`: `200`, then the two rule IDs `913100` (scanner User-Agent) and `949110` (anomaly score 5 reached).

Check 3, the same request in `block` mode. Switch the mode, recreate the scheduler, wait for the new reload, repeat:

```bash
sed -i 's/SECURITY_MODE: "detect"/SECURITY_MODE: "block"/' docker-compose.yml
docker compose up -d bw-scheduler
timeout 180 bash -c 'until docker compose logs bw-scheduler 2>&1 | grep -q "Successfully reloaded bunkerweb"; do sleep 3; done'
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: app.example.com' -A 'sqlmap/1.7' "http://127.0.0.1:${BW_HTTP_PORT:-80}/"
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: app.example.com' "http://127.0.0.1:${BW_HTTP_PORT:-80}/"
docker compose logs bunkerweb 2>&1 | grep -c 'ModSecurity: Access denied with code 403 (phase 2)'
```

Expected in `block`: `403` for the scanner request, `200` for the plain one, and a count of at least 1 for the denial line (rule `949110`).

Observed on 2026-10-05 (images 1.6.15, ports 18080 and 18443, `BW_AUTO_LETS_ENCRYPT=no`): detect `200` with both rule IDs, block `403`, plain request `200`.

Clean up a test run with `docker compose down -v`. That deletes `bw-storage`.

## Traps

- **Settings on the wrong container.** The docs say the scheduler is where 1.6 settings live and that it pushes the configuration to `bunkerweb`. Put service settings on `bw-scheduler`; only `API_*` and `KEEP_CONFIG_ON_RESTART` belong on `bunkerweb`.
- **Scheduler cannot reach the instance.** The site then answers `200` with BunkerWeb's "Generating..." loading page instead of your app. Two causes, both reproduced on 1.6.15:
  - `API_WHITELIST_IP` does not cover the scheduler's subnet. `bunkerweb` logs `[API] can't validate access from IP <ip> : IP is not in API_WHITELIST_IP`.
  - `API_TOKEN` differs between the two containers. `bunkerweb` logs `[API] can't validate API token from IP <ip> : invalid API token`.
  - In both cases the scheduler logs `Can't send API request to http://bunkerweb:5000/custom_configs : Connection error` and `Error while sending /etc/bunkerweb/configs to BunkerWeb instances`.
- **Let's Encrypt on a test host.** `AUTO_LETS_ENCRYPT=yes` needs public DNS for the domain and port 80 reachable from the Internet. When issuance fails the scheduler logs `Failed to generate certificate(s) for app.example.com` and plain HTTP answers `301` to HTTPS, so a test `curl` over HTTP does not return your app. Use `USE_LETS_ENCRYPT_STAGING: "yes"` while testing, and `BW_AUTO_LETS_ENCRYPT=no` for a local run.
- **A placeholder e-mail address is rejected.** With `EMAIL_LETS_ENCRYPT: "you@yourdomain.tld"` the ACME server answered `believes you@yourdomain.tld is an invalid email address`. Use a real address.
- **Scheduler jobs that download data** (GeoIP databases, blocklists) log errors when the container has no outbound DNS. They do not stop the proxy.
- **`docker compose down -v` deletes `bw-storage`**, which holds the database and the backups. Back up before using `-v`.
- **Bind-mounting `/data`.** The scheduler runs as UID 101, GID 101. A host folder must be writable by that user.
