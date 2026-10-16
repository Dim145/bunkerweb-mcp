# BunkerWeb on Linux packages

Verified at v1.6.15. Source: `docs/integrations.md` (Linux), `docs/quickstart-guide.md`, `docs/upgrading.md`, and `src/linux/scripts/` (`postinstall.sh`, `bunkerweb-scheduler.sh`) and `src/linux/*.service`. Not run on a Linux host in this verification: the commands come from the docs and the package scripts.

On Linux nothing runs in a container. Three systemd services share one host:

- `bunkerweb`: nginx with ModSecurity and the Lua plugins.
- `bunkerweb-scheduler`: holds the settings, generates the configuration and reloads `bunkerweb`.
- `bunkerweb-ui`: the web UI and its setup wizard. Optional.

Supported systems at 1.6.15: Debian 12 and 13, Ubuntu 22.04, 24.04 and 26.04, Fedora 43 and 44, and RHEL, CentOS, Rocky and AlmaLinux 8, 9 and 10, on amd64 and arm64. The packages need NGINX 1.30.5: the official nginx.org build on Debian, Ubuntu and the RHEL family, and Fedora's own 1.30.5 package on Fedora.

## Prerequisites

- root or `sudo`, and one of the systems above.
- Ports 80 and 443 free. For Let's Encrypt, public DNS for the domain and port 80 reachable.
- Your app reachable from the host, for example on `127.0.0.1:8080`. BunkerWeb takes ports 80 and 443 itself.

## Install

The easy-install script handles the NGINX pin, the repositories and the services. Download the release's script and its checksum, verify, then run it:

```bash
curl -fsSL -O https://github.com/bunkerity/bunkerweb/releases/download/v1.6.15/install-bunkerweb.sh
curl -fsSL -O https://github.com/bunkerity/bunkerweb/releases/download/v1.6.15/install-bunkerweb.sh.sha256
sha256sum -c install-bunkerweb.sh.sha256
chmod +x install-bunkerweb.sh
sudo ./install-bunkerweb.sh --version 1.6.15
```

Do not run the script if `sha256sum -c` fails. Run without flags for the interactive menu; `--yes` accepts the defaults (full stack, wizard enabled), `--no-wizard` skips the setup wizard, `--worker` installs only the BunkerWeb instance, `--manager` the scheduler and UI, and `--dry-run` prints the plan. The script refuses to be piped: always run the downloaded file.

The package-manager route (add the nginx.org repository, pin `nginx` to 1.30.5, install `bunkerweb=1.6.15` with `apt`, or `bunkerweb-1.6.15` with `dnf`, then hold both packages) is in [docs/integrations.md at v1.6.15](https://github.com/bunkerity/bunkerweb/blob/v1.6.15/docs/integrations.md#linux). Follow it there instead of copying commands from memory.

## Where settings go

- **Wizard route (default).** Open `https://<server>/setup`, create the admin account and add services in the UI. `/etc/bunkerweb/variables.env` then only holds bootstrap values (`MULTISITE=yes`, `SERVER_NAME=`, ports, DNS resolvers); services live in the database.
- **File route.** Install with `--no-wizard` (or `export UI_WIZARD=no` for the package route) and edit `/etc/bunkerweb/variables.env`. Services, per-service prefix and values follow the same rules as [docker.md](docker.md#per-service-settings):

```conf
MULTISITE=yes
SERVER_NAME=app.example.com
DISABLE_DEFAULT_SERVER=yes
SECURITY_MODE=detect
AUTO_LETS_ENCRYPT=yes
EMAIL_LETS_ENCRYPT=you@yourdomain.tld
app.example.com_USE_REVERSE_PROXY=yes
app.example.com_REVERSE_PROXY_URL=/
app.example.com_REVERSE_PROXY_HOST=http://127.0.0.1:8080
```

- `/etc/bunkerweb/scheduler.env` and `ui.env` hold settings for those two services. The scheduler reads `variables.env` first and `scheduler.env` after it, so `scheduler.env` wins on a conflict.
- Split installs (`--manager`, `--worker`) need the same database on the scheduler and UI, and the worker's `API_WHITELIST_IP` must admit the manager.

## Apply a change

After editing `/etc/bunkerweb/variables.env`:

```bash
sudo systemctl restart bunkerweb-scheduler
```

That is enough to regenerate the configuration and reload without downtime. Changes to listening ports need `sudo systemctl restart bunkerweb` too. Check:

```bash
systemctl status bunkerweb bunkerweb-scheduler
sudo journalctl -u bunkerweb-scheduler --no-pager | tail -20
```

Log files are in `/var/log/bunkerweb/`. A fresh install without the wizard may start from a placeholder `variables.env` containing `IS_LOADING=yes`; delete that line when your configuration is ready, or the instance stays on its loading configuration.

## Upgrade

Full procedure: [docs/upgrading.md at v1.6.15](https://github.com/bunkerity/bunkerweb/blob/v1.6.15/docs/upgrading.md). The easy route reuses the install script, which backs up the database first, stops the three services, swaps the package and leaves `variables.env` untouched:

```bash
sudo ./install-bunkerweb.sh --version 1.6.15 --dry-run
sudo ./install-bunkerweb.sh --version 1.6.15 --yes
```

Run `--dry-run` first. Add `--backup-dir <path>` to choose where the backup goes. The installed version is in `/usr/share/bunkerweb/VERSION`. There is no downgrade migration: roll back by restoring the backup and reinstalling the old package.

Manual backup before any manual upgrade:

```bash
sudo mkdir -p /var/backups/bunkerweb
sudo BACKUP_DIRECTORY=/var/backups/bunkerweb bwcli plugin backup save
```

The backup directory must exist before the command runs; `bwcli` fails with `Backup directory ... does not exist` otherwise (seen on the container build of the same CLI).

## Verify

Same three checks as [docker.md](docker.md#verify). On the host itself:

```bash
systemctl is-active bunkerweb bunkerweb-scheduler
curl -sS -i -k --resolve app.example.com:443:127.0.0.1 https://app.example.com/ | grep -iE '^(HTTP/|server:|x-content-type-options:)'
curl -sS -k -o /dev/null -w '%{http_code}\n' --resolve app.example.com:443:127.0.0.1 -A 'sqlmap/1.7' https://app.example.com/
```

Expected: `active` twice, `HTTP/2 200` (`HTTP/1.1 200 OK` when the `HTTP2` setting is off) and `X-Content-Type-Options: nosniff` with no `Server:` line, and `200` for the scanner request in `detect` mode. After switching `SECURITY_MODE=block` and restarting the scheduler it returns `403`. The config above turns on Let's Encrypt, so plain HTTP answers `301` to HTTPS by design (`AUTO_REDIRECT_HTTP_TO_HTTPS` defaults to `yes`), which is why the probes use HTTPS with the right SNI. Before the certificate is issued HTTPS serves BunkerWeb's default self-signed certificate: `-k` is needed until then, and can be dropped afterwards.

## Traps

- **The wrong nginx.** On Debian, Ubuntu and the RHEL family BunkerWeb needs the nginx.org build, pinned to the version the docs name; the docs say packages from other repositories and self-compiled nginx do not work with the prebuilt BunkerWeb packages.
- **`apt upgrade` or `dnf upgrade` moves nginx or bunkerweb.** Hold both packages (`apt-mark hold nginx bunkerweb`, or `dnf versionlock`). The installer re-applies the holds after an upgrade.
- **Editing `variables.env` while the wizard owns the services.** The UI stores services in the database. Use the UI, or install without the wizard and own the file.
- **Manager and worker installs.** The worker only accepts API calls from addresses in its `API_WHITELIST_IP`; the installer asks for the manager IP (`--manager-ip` when unattended).
- **File permissions.** `/etc/bunkerweb/variables.env` is `root:nginx`, mode 660. Edit it with `sudo`, and keep that owner and mode.
