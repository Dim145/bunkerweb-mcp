# Forgejo behind BunkerWeb

No template exists in the template hub for this app. Everything below was found by running it live against BunkerWeb 1.6.15, see `## Verified live`.

- **Upstream and URL.** `REVERSE_PROXY_HOST` points at the container's port `3000`. Set Forgejo's `ROOT_URL` to the public address: the LFS batch answer built its upload and download links from it. No WebSocket is needed; the notification stream is Server-Sent Events on `/user/events` and it passed with the default proxy settings.
- **Method allow-list.** The API, LFS and package registry use `PUT`, `PATCH` and `DELETE`. With the default `ALLOWED_METHODS` (`GET|POST|HEAD|QUERY`) those requests were scored by rule `949110` in detect mode. Use `GET|POST|HEAD|OPTIONS|PUT|DELETE|PATCH` (`OPTIONS` was not exercised). This value drops the default `QUERY`; no flow here used it, and `|QUERY` at the end keeps it.
- **Upload size.** `MAX_CLIENT_SIZE` defaults to `10m`. A 22 MB `git push`, a 25 MB package `PUT`, a 25 MB release asset and a 21 MB web attachment all got `413`. The test used `100m`; set it above your largest push, and use LFS for big files.
- **Rate limit.** `LIMIT_REQ_RATE` defaults to `2r/s` per URL. In block mode it answered `429` to the web login `POST`, and a first fetch of a repository made `info/refs` requests above that rate. The test used `20r/s`.
- **Bans.** `BAD_BEHAVIOR_STATUS_CODES` counts `403`, `404` and `429`, ten in 60 seconds bans the client IP for a day (`bwcli unban <ip>`), and `401` is counted too. Add the exclusions below before block mode, or a first repository fetch blocks its own user.

## CRS exclusions

Git over HTTPS is the first thing CRS blocks: every smart-HTTP and LFS URL contains `.git/`. Rule `930130` (restricted file, target `REQUEST_FILENAME`) and `920420` (content type `application/x-git-upload-pack-request`, `application/vnd.git-lfs+json`, `application/octet-stream`) each score on clone, push, LFS and package uploads. Rule `920440` rejects the file extension in URLs such as `/contents/scripts/install.sh`. Issue, comment and file text is code by nature; rules `930100`-`930120`, `932xxx`, `933xxx` and `941xxx` fired on shell, PHP and HTML snippets.

Custom config of type `modsec-crs` (phase 1 rules; environment form `<server_name>_CUSTOM_CONF_MODSEC_CRS_forgejo`):

```text
SecRule REQUEST_FILENAME "@rx ^/[^/]+/[^/]+\.git/(?:info/refs|git-upload-pack|git-receive-pack|info/lfs/.+)$" \
    "id:10000200,phase:1,pass,nolog,t:none,t:normalizePath,chain,ctl:ruleRemoveTargetById=930130;REQUEST_FILENAME"
SecRule REQUEST_METHOD "@rx ^(?:GET|POST|PUT)$" "t:none,nolog"
SecRule REQUEST_FILENAME "@rx ^/(?:[^/]+/[^/]+\.git/(?:git-upload-pack|git-receive-pack|info/lfs/.+)|api/packages/[^/]+/.+)$" \
    "id:10000201,phase:1,pass,nolog,t:none,t:normalizePath,chain,ctl:ruleRemoveById=920420"
SecRule REQUEST_METHOD "@rx ^(?:POST|PUT)$" "t:none,nolog"
SecRule REQUEST_FILENAME "@rx ^/(?:api/v1/repos/[^/]+/[^/]+/contents/.+|[^/]+/[^/]+/(?:src|raw|blame|_new|_edit|_delete|_upload|commits)/.+)$" \
    "id:10000202,phase:1,pass,nolog,t:none,t:normalizePath,chain,ctl:ruleRemoveById=920440"
SecRule REQUEST_METHOD "@rx ^(?:GET|HEAD|POST|PUT|PATCH|DELETE)$" "t:none,nolog"
```

Custom config of type `modsec`, for the text fields (environment form `<server_name>_CUSTOM_CONF_MODSEC_forgejo_text`). Repeat the `ctl:` line for each tag in `attack-rce`, `attack-lfi`, `attack-xss`, `attack-injection-php` and for each field; the sample shows one of each:

```text
SecRule REQUEST_FILENAME "@rx ^/api/v1/repos/[^/]+/[^/]+/(?:issues|pulls|contents)(?:/.*)?$" \
    "id:10000210,phase:1,pass,nolog,t:none,t:normalizePath,chain,\
    ctl:ruleRemoveTargetByTag=attack-rce;ARGS:json.body,ctl:ruleRemoveTargetByTag=attack-xss;ARGS:json.title"
SecRule REQUEST_METHOD "@rx ^(?:POST|PUT|PATCH)$" "t:none,nolog"
```

The tested fields were `ARGS:json.body`, `json.title`, `json.content`, `json.message` on those API routes, and `ARGS:content`, `title`, `commit_summary`, `commit_message` on `issues/new`, `issues/<n>/comments`, `pulls/<n>/comments`, `_new/...` and `_edit/...`. `attack-sqli` is deliberately not listed: no `942xxx` rule fired on code snippets, and a SQL injection string in the excluded field still got `403`. In a Compose `environment:` block write each `$` as `$$`. A target regex (`ARGS:/re/`) loads without error and does nothing at 1.6.15, so list the field names; `ctl:ruleRemoveTargetByTag` and `ctl:ruleRemoveTargetById` with a literal name or `REQUEST_FILENAME` do work.

## Verified live

Forgejo 16.0.5 (`codeberg.org/forgejo/forgejo:16.0.5`, SQLite), BunkerWeb 1.6.15, tested 2026-10-06 with a self-signed certificate (`GENERATE_SELF_SIGNED_SSL=yes`), the settings and the exclusions above.

| Flow                                                            | Detect, defaults                 | Block, settings only                                                 | Block, final |
| --------------------------------------------------------------- | -------------------------------- | -------------------------------------------------------------------- | ------------ |
| Pages, assets, `/api/healthz`, web login, settings pages        | pass                             | pass (login `429` until the rate limit is raised)                    | pass         |
| API: token, repo, issue, comment, contents, `PATCH`, branch     | pass                             | `403` on issue, comment and contents with shell, PHP or HTML text    | pass         |
| Web forms: new issue, comment, new file with shell and PHP text | scores logged                    | not run without the exclusions                                       | pass         |
| Clone over HTTPS, 22 MB `git push`, re-clone, sha256 equal      | `413`                            | `403`                                                                | pass         |
| LFS batch, 22 MB upload, verify, download                       | not verified (test script error) | `403`                                                                | pass         |
| Generic package `PUT` 25 MB, `GET`, `DELETE`                    | `413`                            | `403`                                                                | pass         |
| Release asset (multipart 25 MB) and web attachment (21 MB)      | `413`                            | pass                                                                 | pass         |
| `/user/events` stream, archive, raw file, delete                | pass                             | stream pass, the rest `403` (client IP banned by the earlier `403`s) | pass         |

The detect column is the first run on default `MAX_CLIENT_SIZE`; the LFS row of that run stopped on a `401` from the test script and was not analysed, so it is not verified. A later detect run, the fourth, passed the LFS flow: batch, 22 MB upload, verify and download with equal sha256. That run's own compose file was not kept (the saved compose files are the final ones), so only what its results and log show is claimed. The body-size limit was raised, since the 22 to 25 MB bodies that got `413` in the first runs went through. The git, LFS and package exclusions above were not active: rules `930130` and `920420` fired on the LFS batch, upload and verify paths, logged only because the run was in detect mode. The pass shows that detect mode refuses nothing there; it does not test the exclusions. The block-final column does. Boundary checks in block mode, each with the rule id in the log: `.git/config` and a `DELETE` on `info/refs` got `403` (`930130`); the odd content type on `/api/v1/user/repos` and a `PATCH` on a package path got `403` (`920420`); `.sh` or `.sql` in `/explore/` and `/api/v1/user/` got `403` (`920440`); the same shell string in another JSON field (`ref`), in `releases` `body`, in a query argument, in a web form field `label_ids` and in `wiki` `content` got `403`; a SQL injection string in the excluded field got `403` (`942100`, `942190`, `942270`, `942360`). A scanner User-Agent got `403`, a plain request `200`, and all 11 flows gave no denied request.

Not tested: SSH, Actions and runners, webhooks, OAuth and OpenID Connect, package registries other than generic, mirrors and migrations, the wiki, and Forgejo behind a real client-IP header.
