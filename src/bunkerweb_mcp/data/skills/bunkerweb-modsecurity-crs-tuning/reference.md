# ModSecurity custom configs: reference

Verified at BunkerWeb v1.6.15. Paths below are relative to the BunkerWeb source tree, with no line numbers because those drift between releases.

## Where files go

Two roots, both included, `/etc/bunkerweb/configs` first.

| Root                | Scope       | Path                                                     |
| ------------------- | ----------- | -------------------------------------------------------- |
| User and database   | Global      | `/etc/bunkerweb/configs/<type>/<name>.conf`              |
| User and database   | One service | `/etc/bunkerweb/configs/<type>/<service_id>/<name>.conf` |
| Rendered by plugins | Global      | `/etc/nginx/<type>/<name>.conf`                          |
| Rendered by plugins | One service | `/etc/nginx/<service_id>/<type>/<name>.conf`             |

The two roots nest their segments in opposite orders. Under `/etc/bunkerweb/configs` the type comes first; under `/etc/nginx` the service comes first. Write your own configs to the first root. The second belongs to plugin templates.

Per-service include lines render only when `MULTISITE=yes`.

`<type>` is one of `modsec`, `modsec-crs`, `crs-plugins-before`, `crs-plugins-after`. All four accept a service scope.

`<service_id>` is the **first token of `SERVER_NAME`**, split on a space.

Global and per-service are additive. Both include lines fire, global first. Neither overrides the other.

In the Docker images the scheduler symlinks `/data/configs` to `/etc/bunkerweb/configs` (`src/scheduler/Dockerfile`), so a bind mount on `/data` reaches the same place.

Whenever the scheduler regenerates custom configs it wipes this tree, rebuilds it from the database, writes every file as `<name>.conf` and forces mode `0640` (`generate_custom_configs` in `src/scheduler/main.py`). It first reads `*.conf` files dropped by hand back into the database with method `manual`, so a hand-written file survives the wipe only if it ends in `.conf`.

Other ways in: the UI Configs page, the API `/configs` endpoints, the env var `<SERVICE>_CUSTOM_CONF_<TYPE>_<NAME>` (`src/common/gen/save_config.py`), Docker labels `bunkerweb.CUSTOM_CONF_<TYPE>_<NAME>`, Swarm configs labelled `bunkerweb.CONFIG_TYPE`, and Kubernetes ConfigMaps annotated `bunkerweb.io/CONFIG_TYPE`.

Name charset through the UI is `^[\w_-]{1,255}$`, so no dots.

## Load order

`USE_MODSECURITY_GLOBAL_CRS=no`, the default. Everything renders per service into `server-http/modsecurity-rules.conf.modsec`.

| #   | Contents                                                                  |
| --- | ------------------------------------------------------------------------- |
| 1   | BunkerWeb engine, body limit and audit directives, rules 200000 to 200006 |
| 2   | `crs-setup-v3.conf` or `crs-setup-v4.conf`                                |
| 3   | `crs-plugins-before`, global then per-service                             |
| 4   | Downloaded CRS plugins, `*-config.conf` then `*-before.conf`              |
| 5   | `modsec-crs`, global then per-service                                     |
| 6   | Rule 900200 from `ALLOWED_METHODS`, whitelist rule 1000                   |
| 7   | **OWASP CRS rules**                                                       |
| 8   | `crs-plugins-after`, global then per-service                              |
| 9   | Downloaded CRS plugins, `*-after.conf`                                    |
| 10  | `modsec`, global then per-service                                         |
| 11  | `SecRuleUpdateActionById` for 949110, 959100 and 911100                   |

Step 11 lands after your `modsec` file, which is why those three rules resist edits made there.

Steps 2 to 9 sit behind `USE_MODSECURITY_CRS=yes`. Step 10 does not, so `modsec` survives with the CRS switched off.

Steps 3 and 8 also require `USE_MODSECURITY_CRS_PLUGINS=yes` **and** a CRS version other than 3.

## Global CRS mode

`USE_MODSECURITY_GLOBAL_CRS=yes` loads the CRS once at `http` scope for rule-loading performance. It changes the rules of the game:

- `modsec-crs`, `crs-plugins-before` and `crs-plugins-after` become global only. The database rejects a service-scoped `modsec-crs` with "Service-scoped modsec-crs configs are not supported when USE_MODSECURITY_GLOBAL_CRS is enabled. Create a global modsec-crs config and scope it with a Host rule instead."
- Service-scoped `crs-plugins-*` gets dropped without a diagnostic.
- Downloaded CRS plugins are never included, though the job still downloads them.
- `modsec` keeps its per-service scope.
- The whitelist rule loses its `USE_WHITELIST` guard and is emitted unconditionally.
- **Evaluation order inverts.** The nginx connector merges the parent (http) rule set after the child (server) one, so within a phase your server-scope `modsec` rules run _before_ the http-scope CRS rules. Every "modsec is too late for a phase 1 target" statement in SKILL.md applies to the default mode only. Rule 900200 also precedes the `modsec-crs` include here, so `tx.allowed_methods` behaves the opposite way.

## Settings

| Setting                                     | Default                               | Context    | Effect                                                                               |
| ------------------------------------------- | ------------------------------------- | ---------- | ------------------------------------------------------------------------------------ |
| `USE_MODSECURITY`                           | `yes`                                 | multisite  | `modsecurity on\|off`                                                                |
| `USE_MODSECURITY_CRS`                       | `yes`                                 | multisite  | Gates CRS setup, rules, plugins, `modsec-crs`, and the 949110/959100/911100 rewrites |
| `USE_MODSECURITY_CRS_PLUGINS`               | `yes`                                 | multisite  | Gates both `crs-plugins-*` types and the download job                                |
| `MODSECURITY_CRS_VERSION`                   | `4`                                   | multisite  | `3`, `4` or `nightly`. `nightly` resolves to 4                                       |
| `MODSECURITY_CRS_PLUGINS`                   | empty                                 | multisite  | Space separated `name`, `name/tag` or URL                                            |
| `USE_MODSECURITY_GLOBAL_CRS`                | `no`                                  | **global** | See above                                                                            |
| `MODSECURITY_SEC_RULE_ENGINE`               | `On`                                  | multisite  | Honoured only when `SECURITY_MODE=block`                                             |
| `MODSECURITY_SEC_AUDIT_ENGINE`              | `RelevantOnly`                        | multisite  | `SecAuditEngine`                                                                     |
| `MODSECURITY_SEC_AUDIT_LOG_PARTS`           | `BCFH`                                | multisite  | Wrapped as `A...Z`; your own `A` and `Z` get stripped                                |
| `MODSECURITY_SEC_AUDIT_LOG_TYPE`            | `Serial`                              | multisite  | `Serial` or `Concurrent`; `Concurrent` also uses the storage directory setting       |
| `MODSECURITY_SEC_AUDIT_LOG_STORAGE_DIR`     | empty                                 | multisite  | `SecAuditLogStorageDir`, rendered only for `Concurrent`                              |
| `MODSECURITY_SEC_AUDIT_LOG`                 | `/var/log/bunkerweb/modsec_audit.log` | multisite  | `SecAuditLog`; must sit under `/var/log/bunkerweb/`                                  |
| `MODSECURITY_SEC_REQUEST_BODY_LIMIT`        | empty                                 | multisite  | Falls back to `MAX_CLIENT_SIZE` when empty                                           |
| `MODSECURITY_REQ_BODY_NO_FILES_LIMIT`       | `131072`                              | multisite  | `SecRequestBodyNoFilesLimit`                                                         |
| `MODSECURITY_SEC_REQUEST_BODY_LIMIT_ACTION` | `Reject`                              | multisite  | Also switches which of 200002 and 200005 get emitted                                 |

## What BunkerWeb sets and what it leaves alone

Without a template, BunkerWeb sets no paranoia level and no anomaly threshold. Both `crs-setup` files ship with every `SecAction 900xxx` commented out, so CRS defaults apply: paranoia level 1, inbound threshold 5, outbound threshold 4. Change them from a `modsec-crs` config.

The `low`, `medium` and `high` templates do set them, through rules 900001 and 900110 in `templates/templates/<name>/configs/modsec/anomaly_score.conf`. Those files are type **`modsec`**, so they load after the CRS. The threshold change works, because 949110 reads it in phase 2. The `high` template's `tx.detection_paranoia_level=2` lands after every phase 1 paranoia guard has already run at level 1, so it only reaches phase 2 rules. Set the paranoia level from `modsec-crs` if you need it in phase 1.

BunkerWeb hardcodes `SecResponseBodyAccess On` and a 524288 byte response body limit. No setting exposes these.

The vendored CRS rules carry BunkerWeb patches: every anomaly scoring action also sets `tx.bunkerweb_*` variables so the Lua reporting layer can read them (see any rule in `src/common/core/modsecurity/files/coreruleset-v4/rules/`). Do not replace the shipped rules with pristine upstream copies.

## Places ModSecurity is off entirely

- `REVERSE_PROXY_MODSECURITY_<n>=no` emits `modsecurity off` for that location.
- Every gRPC location disables it unconditionally.

No custom rule runs in either.
