# BunkerWeb on Docker with autoconf

Verified at v1.6.15. Source: `docs/integrations.md` (Docker autoconf), `src/autoconf/controllers/DockerController.py`, and a live run of the two compose files below on 2026-10-05.

Autoconf is the [Docker integration](docker.md) with one extra container. `bw-autoconf` watches Docker events and turns the labels on your containers into services, so adding or changing a site needs no edit of the BunkerWeb stack and no restart of BunkerWeb. Read [docker.md](docker.md) first for the instance API, `API_WHITELIST_IP` and `API_TOKEN`; they work the same here.

## Prerequisites

- Docker Engine and Compose v2.
- A real database: MariaDB, MySQL or PostgreSQL. Autoconf and the scheduler must share one `DATABASE_URI`; SQLite does not work for this.
- Autoconf implies multisite mode. `MULTISITE: "yes"` on the scheduler is mandatory.
- Access to the Docker socket. The stack below puts a socket proxy in front of it so `bw-autoconf` can only read containers.

## Compose file: the BunkerWeb stack

Save as `bunkerweb-stack.yml`. Replace both `changeme` passwords (they must match) and keep every BunkerWeb tag identical.

```yaml
x-bw-env: &bw-env
  AUTOCONF_MODE: "yes"
  API_WHITELIST_IP: "127.0.0.0/8 203.0.113.0/24"
  API_TOKEN: "${BW_API_TOKEN:?set BW_API_TOKEN before docker compose up}"

services:
  bunkerweb:
    image: bunkerity/bunkerweb:1.6.15
    ports:
      - "80:8080/tcp"
      - "443:8443/tcp"
      - "443:8443/udp" # QUIC
    labels:
      - "bunkerweb.INSTANCE=yes" # mandatory: how autoconf finds the instance
    environment:
      <<: *bw-env
    restart: unless-stopped
    networks:
      - bw-universe
      - bw-services

  bw-scheduler:
    image: bunkerity/bunkerweb-scheduler:1.6.15
    environment:
      <<: *bw-env
      BUNKERWEB_INSTANCES: "" # instances are discovered by autoconf
      SERVER_NAME: "" # services come from labels
      MULTISITE: "yes"
      SECURITY_MODE: "detect" # default for every service; switch to "block" after reading the logs
      DATABASE_URI: "mariadb+pymysql://bunkerweb:changeme@bw-db:3306/db"
    volumes:
      - bw-storage:/data
    restart: unless-stopped
    networks:
      - bw-universe
      - bw-db

  bw-autoconf:
    image: bunkerity/bunkerweb-autoconf:1.6.15
    depends_on:
      - bunkerweb
      - bw-docker
    environment:
      AUTOCONF_MODE: "yes"
      DATABASE_URI: "mariadb+pymysql://bunkerweb:changeme@bw-db:3306/db"
      DOCKER_HOST: "tcp://bw-docker:2375"
    restart: unless-stopped
    networks:
      - bw-universe
      - bw-docker
      - bw-db

  bw-docker:
    image: tecnativa/docker-socket-proxy:v0.5.0
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      CONTAINERS: "1"
      LOG_LEVEL: "warning"
    restart: unless-stopped
    networks:
      - bw-docker

  bw-db:
    image: mariadb:11
    command: --max-allowed-packet=67108864
    environment:
      MYSQL_RANDOM_ROOT_PASSWORD: "yes"
      MYSQL_DATABASE: "db"
      MYSQL_USER: "bunkerweb"
      MYSQL_PASSWORD: "changeme"
    volumes:
      - bw-data:/var/lib/mysql
    restart: unless-stopped
    networks:
      - bw-db

volumes:
  bw-data:
  bw-storage:

networks:
  bw-universe:
    name: bw-universe
    ipam:
      config:
        - subnet: 203.0.113.0/24 # example range, use an unused subnet; keep in sync with API_WHITELIST_IP
  bw-services:
    name: bw-services
  bw-docker:
    name: bw-docker
  bw-db:
    name: bw-db
```

Rootless Docker mounts `$XDG_RUNTIME_DIR/docker.sock` instead of `/var/run/docker.sock`. The database sits on `bw-db` only, never on `bw-universe`.

## Compose file: a protected app

Save as `myapp.yml`, in any directory. The app joins the external `bw-services` network, publishes no port, and carries its BunkerWeb settings as labels:

```yaml
services:
  myapp:
    image: bunkerity/bunkerweb-hello:v1.0 # stand-in for your service: any image that listens on 8080
    networks:
      - bw-services
    labels:
      - "bunkerweb.SERVER_NAME=app.example.com"
      - "bunkerweb.USE_REVERSE_PROXY=yes"
      - "bunkerweb.REVERSE_PROXY_URL=/"
      - "bunkerweb.REVERSE_PROXY_HOST=http://myapp:8080"
      - "bunkerweb.AUTO_LETS_ENCRYPT=yes"
      - "bunkerweb.EMAIL_LETS_ENCRYPT=you@yourdomain.tld"

networks:
  bw-services:
    external: true
    name: bw-services
```

Start both:

```bash
export BW_API_TOKEN="$(openssl rand -hex 24)"
docker compose -f bunkerweb-stack.yml up -d
docker compose -f myapp.yml up -d
```

## Where settings go

- **Per service: labels on the app container.** The label is `bunkerweb.<SETTING>=<value>` with the plain setting name and no host prefix. `bunkerweb.SERVER_NAME` is what makes a container a service; a container without it is ignored.
- **Defaults for every service: the `bw-scheduler` environment**, for example `SECURITY_MODE` above. A label on one service overrides the default for that service only.
- **Custom nginx or ModSecurity snippets: labels named `bunkerweb.CUSTOM_CONF_<TYPE>_<NAME>`**, with `<TYPE>` one of `SERVER_HTTP`, `SERVER_STREAM`, `MODSEC`, `MODSEC_CRS`, `CRS_PLUGINS_BEFORE`, `CRS_PLUGINS_AFTER`. They attach to the service named by `bunkerweb.SERVER_NAME` on the same container. Which type loads when is in the `bunkerweb-modsecurity-crs-tuning` skill.
- **Namespaces:** `bunkerweb.NAMESPACE=<name>` on the instance, the services and the controller's `NAMESPACES` environment variable split one Docker host into several independent clusters. There can be one database and one scheduler per namespace.
- **Opt a container out:** `DOCKER_IGNORE_LABELS` on `bw-autoconf` lists labels (or their suffixes) that make autoconf skip any container carrying them.

## Apply a change

- Change a label: edit `myapp.yml` and run `docker compose -f myapp.yml up -d`. Compose recreates the container, autoconf sees the Docker event, the scheduler regenerates the configuration and reloads BunkerWeb. Nothing else restarts.
- Change a default on the scheduler: edit `bunkerweb-stack.yml` and run `docker compose -f bunkerweb-stack.yml up -d bw-scheduler`.
- Check the result: `docker compose -f bunkerweb-stack.yml logs bw-scheduler 2>&1 | grep 'Successfully reloaded bunkerweb'`.

Observed on 2026-10-05: after recreating the app with a new label the change was live in under 10 seconds, and `bunkerweb.SECURITY_MODE=block` on one service turned a scanner `User-Agent` from `200` into `403` while the scheduler default stayed `detect`.

Services created from labels are owned by autoconf: the web UI shows them but does not let you delete them. When a labelled container disappears autoconf deletes its service. Set `AUTOCONF_DISABLE_CLEANUP: "yes"` on `bw-autoconf` to keep removed services as drafts instead.

## Upgrade

Full procedure: [docs/upgrading.md at v1.6.15](https://github.com/bunkerity/bunkerweb/blob/v1.6.15/docs/upgrading.md). Back up with `bwcli` inside the scheduler (the backup directory must already exist), change the tag on `bunkerweb`, `bw-scheduler`, `bw-autoconf` (and `bw-ui` if present) together, then `docker compose -f bunkerweb-stack.yml pull && docker compose -f bunkerweb-stack.yml up -d`. The commands are in [docker.md](docker.md#upgrade); add `-f bunkerweb-stack.yml`.

## Verify

Same checks as [docker.md](docker.md#verify), run against the autoconf stack. The mode is `detect` by default, so a scanner User-Agent passes and is logged. Switch a single service to `block` by adding the label `bunkerweb.SECURITY_MODE=block` to `myapp.yml` and recreating the app:

```bash
curl -sS -i -H 'Host: app.example.com' "http://127.0.0.1/" | grep -iE '^(HTTP/|server:|x-content-type-options:)'
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: app.example.com' -A 'sqlmap/1.7' "http://127.0.0.1/"
```

## Traps

- **No `bunkerweb.INSTANCE=yes` label on the instance.** Autoconf finds no instance and nothing is pushed.
- **`MULTISITE` not `yes`, or `BUNKERWEB_INSTANCES` filled in.** The scheduler must run multisite and leave the instance list empty; autoconf supplies it.
- **App not on `bw-services`.** The service answers `502` and `bunkerweb` logs `<name> could not be resolved (2: Server failure)` for the upstream host. Reproduced on 1.6.15.
- **Different `DATABASE_URI` on the scheduler and autoconf.** The docs say autoconf's value must match the scheduler's; with two databases the scheduler never sees the services.
- **A mistyped label is dropped with a warning.** Autoconf logs `Variable <NAME>: <value> is not a valid autoconf setting (missing), ignoring it` (seen for a deliberately misspelled `USE_REVERSE_PROXY` label) and carries on, so the service comes up without the setting. Grep the autoconf log after every label edit.
- **Autoconf only reads.** It never edits containers. The socket proxy in the stack grants `CONTAINERS: "1"` and nothing else.
