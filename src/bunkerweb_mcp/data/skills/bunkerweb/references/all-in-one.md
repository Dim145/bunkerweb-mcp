# BunkerWeb all-in-one image

Verified at v1.6.15. Source: `docs/integrations.md` (All-In-One), `docs/quickstart-guide.md`, `src/all-in-one/entrypoint.sh`, `docs/upgrading.md`, and a live run of the compose file below on 2026-10-05.

One container runs nginx and BunkerWeb, the scheduler, the web UI, an embedded Redis and, when enabled, the API and CrowdSec. State lives in the `/data` volume. It is the quickest way to try BunkerWeb and a fair choice for one host; it has no separate scheduler to scale. For several instances or autoconf use [docker.md](docker.md) or [autoconf.md](autoconf.md).

## Prerequisites

- Docker Engine and Compose v2.
- Ports 80 and 443 (TCP) and 443 (UDP, QUIC) free on the host. Container ports are 8080, 8443 and 8443/udp.
- For Let's Encrypt: public DNS and port 80 reachable, as in [docker.md](docker.md#traps).
- A writable `/data`. The container runs as UID 101, GID 101, so a bind-mounted folder must be writable by that user; a named volume needs nothing.

## Two ways to configure it

1. **Web UI wizard (default).** Run the container with only the volume and ports. `SERVICE_UI=yes` is the default, so the setup wizard starts on first run. Open `https://<your-host>/`, create the admin account, then add services in the UI. Port 7000 reaches the UI without BunkerWeb in front; do not publish it in production.
2. **Environment variables.** Put the same settings you would give the scheduler in the container environment. Set `SERVICE_UI: "no"` if you do not want the UI. `MULTISITE` defaults to `yes` in this image, so per-service settings carry the `<server_name>_` prefix.

## Compose file (environment-driven)

Replace `app.example.com`, the e-mail and `myapp`. The app joins the same network as the container and is never published.

```yaml
services:
  bunkerweb-aio:
    image: bunkerity/bunkerweb-all-in-one:1.6.15
    container_name: bunkerweb-aio
    ports:
      - "${BW_HTTP_PORT:-80}:8080/tcp"
      - "${BW_HTTPS_PORT:-443}:8443/tcp"
      - "${BW_HTTPS_PORT:-443}:8443/udp" # QUIC
    environment:
      SERVICE_UI: "no" # set to "yes" to keep the web UI and its setup wizard
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
      - bw-storage:/data
    restart: unless-stopped
    networks:
      - bw-services

  myapp: # stand-in for your service: any image that listens on 8080
    image: bunkerity/bunkerweb-hello:v1.0
    restart: unless-stopped
    networks:
      - bw-services

volumes:
  bw-storage:

networks:
  bw-services:
```

The same container as one command, for the UI-wizard route:

```bash
docker run -d \
  --name bunkerweb-aio \
  -v bw-storage:/data \
  -p 80:8080/tcp \
  -p 443:8443/tcp \
  -p 443:8443/udp \
  bunkerity/bunkerweb-all-in-one:1.6.15
```

## Per-service settings

Add hostnames to `SERVER_NAME` and prefix each per-service (`multisite`) setting with its host, as in [docker.md](docker.md#per-service-settings). Built-in services are switched with `SERVICE_UI`, `SERVICE_SCHEDULER`, `SERVICE_API` (default `no`), `AUTOCONF_MODE` (default `no`), `USE_REDIS` (default `yes`) and `USE_CROWDSEC` (default `no`). `HIDE_SERVICE_LOGS` silences chosen services in `docker logs`.

## Apply a change

Environment settings are read at container start: edit the compose file and run `docker compose up -d`, which recreates the container. Settings you change in the web UI are stored in `/data` and survive recreation. The container logs reach `docker logs`; `access.log`, `error.log` and `modsec_audit.log` are also real files under `/var/log/bunkerweb/` inside it.

## Upgrade

Full procedure: [docs/upgrading.md at v1.6.15](https://github.com/bunkerity/bunkerweb/blob/v1.6.15/docs/upgrading.md). Never delete the `/data` volume. Back up, then replace the container:

```bash
docker exec -e BACKUP_DIRECTORY=/data/backups bunkerweb-aio mkdir -p /data/backups
docker exec -e BACKUP_DIRECTORY=/data/backups bunkerweb-aio bwcli plugin backup save
```

Change the image tag, then `docker compose pull && docker compose up -d`, or for `docker run` stop and remove the container, pull the new tag and run the same command again with the same `-v`, `-p` and `-e` options. Confirm with `docker exec bunkerweb-aio cat /usr/share/bunkerweb/VERSION`. If you use an external database through `DATABASE_URI`, back that up with its own tooling too.

## Verify

The same checks as [docker.md](docker.md#verify), against the published port. This image has no separate scheduler log: wait until `docker compose ps` shows `(healthy)` (about a minute) instead of grepping for the reload line.

```bash
export BW_AUTO_LETS_ENCRYPT=no BW_HTTP_PORT=18080 BW_HTTPS_PORT=18443
docker compose up -d
sleep 70
docker compose ps
curl -sS -i -H 'Host: app.example.com' "http://127.0.0.1:${BW_HTTP_PORT:-80}/" | grep -iE '^(HTTP/|server:|x-content-type-options:)'
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: app.example.com' -A 'sqlmap/1.7' "http://127.0.0.1:${BW_HTTP_PORT:-80}/"
```

Expected: `HTTP/1.1 200 OK` and `X-Content-Type-Options: nosniff` with no `Server:` line, then `200` for the scanner request in `detect` mode. Set `SECURITY_MODE: "block"`, run `docker compose up -d`, wait for `(healthy)` and the scanner request returns `403`.

Observed on 2026-10-05 (image 1.6.15, ports 18080 and 18443, `BW_AUTO_LETS_ENCRYPT=no`): `200` with the headers, then `200` for the scanner request in `detect` mode. The `block` result is the one shown for the scheduler stack in [docker.md](docker.md#verify); it was not re-run on this image.

## Traps

- **Two similar API settings.** The instance API uses `API_WHITELIST_IP` and `API_TOKEN`. The embedded external API (`SERVICE_API=yes`) uses `API_WHITELIST_IPS` (with an S), `API_USERNAME` and `API_PASSWORD`. They are different settings with different defaults.
- **Do not publish 8888 or 7000 on the Internet.** Reach the API and the UI through BunkerWeb as a reverse-proxied service.
- **Embedded Redis starts only when `USE_REDIS=yes` and `REDIS_HOST` is left at its default.** Setting `REDIS_HOST` points BunkerWeb at an external server and the embedded one does not launch.
- **One container is one failure domain.** A restart drops traffic for the whole stack.
