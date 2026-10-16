# Tomcat behind BunkerWeb

Template: https://github.com/bunkerity/bunkerweb-templates/tree/main/templates/tomcat (read at hub commit 4ba433a, 2026-09-19). It sets the reverse proxy, `MAX_CLIENT_SIZE=100m` and `ALLOWED_METHODS=GET|POST|HEAD|PUT|DELETE|OPTIONS`, which drops the default `QUERY` (no flow used it). Run live against 1.6.15 it needed one setting and, for the manager API only, one exclusion.

## What Tomcat needs

- **WebSocket.** The template does not enable it. Without `REVERSE_PROXY_WS=yes` the handshake to `/examples/websocket/echoAnnotation` answered `404` (Tomcat saw a plain `GET`), in detect and block mode alike. With it: `101`, then the echo.
- **Methods.** The template's list is enough for servlets and the manager text API. `PATCH` is not in it, so add it if your app uses it.
- **Upload size.** `MAX_CLIENT_SIZE=100m` passed 21 MB WAR uploads, both as a raw `PUT` and as a multipart form post to the manager page.
- **Manager API content type.** `PUT /manager/text/deploy` sends the WAR as `application/octet-stream`, and CRS rule 920420 answers `403`. The fix is a `modsec-crs` config named `tomcat-manager-deploy`, scoped to that path and method (rule 920420 runs in phase 1):

  ```text
  SecRule REQUEST_FILENAME "@rx ^/manager/text/deploy$" "id:10000040,phase:1,pass,nolog,t:none,t:normalizePath,chain,ctl:ruleRemoveTargetById=920420;REQUEST_HEADERS:Content-Type"
  SecRule REQUEST_METHOD "@streq PUT" "t:none,nolog"
  ```

  Any content type is then accepted on that path, and the body is not inspected as a form. Do not publish `/manager` to the Internet: restrict it by address, or leave it off the proxy.

- **Tomcat side.** The bundled `examples`, `docs` and `manager` apps restrict clients to localhost with a `RemoteAddrValve`. Behind a proxy the client is BunkerWeb, so they answer `403` until the valve is relaxed; do that only on a test instance.
- **Response inspection.** CRS 953100 ("PHP Information Leakage") matched the words `Division by zero` in the response of the example page `basic-arithmetic.jsp`; in block mode BunkerWeb dropped the connection. No exclusion was added, because the examples webapp should not run in production. An application page that prints that text would hit it too.

## Verified live

Tomcat 11.0.26 (`tomcat:11.0.26-jre25`), BunkerWeb 1.6.15 (Docker), CRS 4.29.0, 2026-10-06.

| Flow                                                                                               | Detect              | Block, template | Block, tuned |
| -------------------------------------------------------------------------------------------------- | ------------------- | --------------- | ------------ |
| ROOT, examples, docs, manager status                                                               | pass                | pass            | pass         |
| Servlet form `POST`, session cookie round trip, manager `serverinfo` and `list`, `HEAD`, `OPTIONS` | pass                | pass            | pass         |
| 21 MB WAR by `PUT /manager/text/deploy`, then the deployed JSP                                     | pass, 920420 logged | `403`           | pass         |
| 21 MB WAR by multipart `/manager/html/upload`, undeploy                                            | pass                | pass            | pass         |
| WebSocket echo                                                                                     | `404`               | `404`           | pass         |

Boundary checks on the tuned stack, all `403` with rule 920420 in the log: `POST` with the same body on `/manager/text/deploy`; `PUT` with `octet-stream` on `/manager/text/list`, `/manager/text/deploy.bak`, `/manager/text/deployer`, the servlet path, and a `/manager/text/../html/deploy` traversal. A SQL injection string in the query of the excluded path is `403` too. A `sqlmap/1.7` agent, SQL injection, XSS, path traversal, command injection and a `${jndi:...}` header all got `403`.

## Not tested

TLS between BunkerWeb and Tomcat, AJP, clustering and session replication, your own WARs and frameworks, and Let's Encrypt.
