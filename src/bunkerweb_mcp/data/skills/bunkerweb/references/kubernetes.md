# BunkerWeb on Kubernetes

Verified at v1.6.15, Helm chart `1.1.0` (appVersion `1.6.15`). Sources: `docs/integrations.md` (Kubernetes), `docs/quickstart-guide.md`, `src/autoconf/controllers/IngressController.py`, and the chart at tag `v1.1.0` of [bunkerweb-helm](https://github.com/bunkerity/bunkerweb-helm) rendered with `helm template`. The chart repository index at `https://repo.bunkerweb.io/charts` lists `1.1.0` with appVersion `1.6.15`. The chart `1.1.0` path was run on minikube by the ingress-nginx migration skill; see its [verified live results](https://github.com/bunkerity/bunkerweb-skills/blob/main/skills/bunkerweb-migrate-ingress-nginx/references/verified-live.md). Other behaviour here is checked against the controller source.

The chart installs BunkerWeb workers, a controller (the `bw-autoconf` image run as an Ingress controller), a scheduler, and by default MariaDB, Redis and the web UI. The controller turns Ingress objects into BunkerWeb services; the scheduler reads the settings, builds the configuration and pushes it to the workers.

## Prerequisites

- Kubernetes 1.19 or later, Helm 3.8 or later, and a PersistentVolume provisioner (MariaDB, Redis and the UI keep data on volumes).
- RBAC for the controller. The chart creates it.
- DNS records for your hosts pointing at the BunkerWeb `LoadBalancer` address.

## Install

Pin the chart version. `1.1.0` is the chart release built for BunkerWeb 1.6.15.

```bash
helm repo add bunkerweb https://repo.bunkerweb.io/charts
helm repo update
helm install bunkerweb bunkerweb/bunkerweb --version 1.1.0 --namespace bunkerweb --create-namespace -f values.yaml
```

A `values.yaml` for a first, safe rollout. The passwords below replace the chart's default `changeme`; use `settings.existingSecret` instead for anything real.

```yaml
settings:
  kubernetes:
    ingressClass: "bunkerweb" # only handle Ingresses of this class
  ui:
    adminPassword: "replace-me"
mariadb:
  config:
    password: "replace-me"
redis:
  config:
    password: "replace-me"
scheduler:
  features:
    global:
      securityMode: "detect" # default for every service; switch to "block" later
    letsEncrypt:
      autoLetsEncrypt: "yes"
      emailLetsEncrypt: "you@yourdomain.tld"
```

With the release named `bunkerweb` the objects are short: Service `bunkerweb-external` (the `LoadBalancer`), Deployments `controller-bunkerweb` and `scheduler-bunkerweb`, and an `IngressClass` named `bunkerweb`. With any other release name each one is `<release>-bunkerweb...`; the quickstart's `mybw-external` is wrong, the Service for release `mybw` is `mybw-bunkerweb-external`.

Get the address to point DNS at. Some clouds publish a hostname instead of an IP; read `.status.loadBalancer.ingress[0].hostname` then.

```bash
kubectl -n bunkerweb get svc bunkerweb-external -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
```

## An Ingress

The controller reads every Ingress of the class and builds one BunkerWeb service per `host`. It derives the reverse proxy itself: `USE_REVERSE_PROXY=yes` and `REVERSE_PROXY_HOST=http://<service>.<namespace>.svc.cluster.local[:port]`, one location per `path`. The backend Service must exist in the Ingress's namespace, or the rule is ignored with a warning. Per-service settings are annotations with the fixed domain `bunkerweb.io`:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shop
  annotations:
    bunkerweb.io/shop.example.com_USE_ANTIBOT: "captcha"
spec:
  ingressClassName: bunkerweb
  rules:
    - host: shop.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: shop
                port:
                  number: 80
```

Apply it in the namespace of the `shop` Service with `kubectl apply -f ingress.yaml`.

The chart sets `KUBERNETES_REVERSE_PROXY_SUFFIX_START=0` on the controller: the first path uses unsuffixed `REVERSE_PROXY_URL` and `REVERSE_PROXY_HOST`, then `_1`, `_2`, and so on. Ingresses with the same primary host and namespace merge into one service, with numbered groups renumbered by content. Scalar annotations apply to the whole host; conflicting values use last-wins and log a warning. Keep host-wide scalar values consistent across those Ingresses. An Ingress from another namespace cannot take over an already-owned host.

Annotation rules, from the controller source:

- `bunkerweb.io/<host>_<SETTING>` applies to that host only. `bunkerweb.io/<SETTING>` without a host applies to every host in that Ingress, which is the same thing when the Ingress has one host. Neither reaches other Ingresses.
- Values are strings, so quote them. The setting names are the ones in `src/common/settings.json` and the plugin `plugin.json` files: `USE_ANTIBOT` takes `no`, `cookie`, `javascript`, `captcha`, `recaptcha`, `hcaptcha`, `turnstile`, `mcaptcha` or `capjs`.
- `SERVER_NAME` cannot be set by annotation; the Ingress `host` sets it. A rule without a `host` is ignored.
- A `tls:` block with a Secret holding `tls.crt` and `tls.key` becomes a custom certificate for that host. Without it, `AUTO_LETS_ENCRYPT` obtains one (the values above turn it on for every service; an Ingress can set `bunkerweb.io/AUTO_LETS_ENCRYPT` itself).

## Where settings go

- **Per service:** Ingress annotations, as above.
- **Defaults for every service:** the chart values under `scheduler.features.*` (for example `global.securityMode`, `letsEncrypt.autoLetsEncrypt`, `antibot.useAntibot`). Any setting without a dedicated key goes on `scheduler.extraEnvs`.
- **Never `bunkerweb.extraEnvs` for service settings.** The scheduler generates the configuration, so settings set only on the worker pods have no effect. The same holds for Redis settings.
- Custom nginx or ModSecurity snippets: a ConfigMap carrying the annotation `bunkerweb.io/CONFIG_TYPE`, plus `bunkerweb.io/CONFIG_SITE` to scope it to one service. Which type loads when is in the `bunkerweb-modsecurity-crs-tuning` skill.

## Apply a change

- Change an annotation: edit the Ingress and `kubectl apply`. The controller sees the event, the scheduler regenerates and the workers reload; nothing restarts.
- Change a default: edit `values.yaml` and run `helm upgrade bunkerweb bunkerweb/bunkerweb --version 1.1.0 --namespace bunkerweb -f values.yaml`. The scheduler pod restarts and re-pushes.
- Check: `kubectl -n bunkerweb logs deploy/controller-bunkerweb` for the controller and `kubectl -n bunkerweb logs deploy/scheduler-bunkerweb` for the scheduler.

## Upgrade

Full procedure: [docs/upgrading.md at v1.6.15](https://github.com/bunkerity/bunkerweb/blob/v1.6.15/docs/upgrading.md). Chart upgrades are `helm repo update`, `helm search repo bunkerweb/bunkerweb --versions` to see which chart carries which appVersion, then `helm upgrade ... --version <new>`. Back up the MariaDB volume first. There is no downgrade migration.

## Verify

```bash
kubectl -n bunkerweb get pods
kubectl get ingressclass bunkerweb
kubectl get ingress shop
lb_ip="$(kubectl -n bunkerweb get svc bunkerweb-external -o jsonpath='{.status.loadBalancer.ingress[0].ip}')"
curl -sS -i -k --resolve shop.example.com:443:"$lb_ip" https://shop.example.com/ | head -12
```

The values above turn on Let's Encrypt, so plain HTTP answers `301` to HTTPS by design (`AUTO_REDIRECT_HTTP_TO_HTTPS` defaults to `yes`) and never reaches antibot or the scanner check: probe over HTTPS. Before the certificate is issued HTTPS serves BunkerWeb's default self-signed certificate, which is why the probes use `-k`; once it is issued, drop `-k`. Expected: every BunkerWeb pod `Running`, the class and the Ingress listed. With `USE_ANTIBOT=captcha` on this host the `curl` gets a `302` to the challenge page (`/challenge` by default, `ANTIBOT_URI`) with BunkerWeb's headers, not the app: that proves the request goes through BunkerWeb and the annotation was applied. Another host of the cluster without the annotation returns its app page, which shows the setting is scoped to `shop.example.com`.

To see the WAF act, send the scanner request to a host that has no antibot annotation:

```bash
curl -sS -k -o /dev/null -w '%{http_code}\n' --resolve other.example.com:443:"$lb_ip" -A 'sqlmap/1.7' https://other.example.com/
```

It returns the page in `detect` mode and `403` once `securityMode` is `block`. If the controller or scheduler log shows nothing, check `kubectl -n bunkerweb logs deploy/controller-bunkerweb` for `Ignoring ingress rule ... service not found` (backend Service missing in the Ingress's namespace).

## Traps

- **`duplicate location` on reload.** A redirect and a generated proxy location for the same path collide: the minikube run hit this with `/old` as both an Ingress path and `REDIRECT_FROM`. Do not generate both locations for that path; inspect the rendered redirect and reverse-proxy configs before retrying.
- **`invalid variable name` on reload.** A pasted ingress-nginx regex such as `/zz(/|$)(.*)` stays a plain location and is also emitted in `X-Forwarded-Prefix`; the minikube run failed the nginx config check. Keep the Ingress path a plain absolute path and put the regex, starting with `^`, in the matching `bunkerweb.io/REVERSE_PROXY_URL` annotation.
- **Another Ingress controller in the cluster.** With `settings.kubernetes.ingressClass` empty (the chart default) the 1.6.15 controller processes Ingresses of every class. The chart's `skipForeignClasses` needs 1.6.16 or later. Set `ingressClass: "bunkerweb"` and `ingressClassName: bunkerweb` on your Ingresses.
- **Default passwords.** The chart ships `changeme` for MariaDB, Redis and the UI admin. Change them or use `settings.existingSecret`.
- **Worker API token.** The chart generates a cluster-wide `API_TOKEN` (`settings.apiToken`) and keeps it in a Secret. Treat it as an admin credential, and do not render the chart with `helm template` in GitOps without setting `settings.apiToken.generate: false` and your own Secret.
- **Quoting.** An annotation value of `yes` or `no` unquoted is a YAML boolean and Kubernetes rejects the object. Quote every value.
- **Wrong annotation prefix.** `bunkerweb.io/` is the only prefix the controller reads. A label is not read.
- **Cluster DNS name.** `DNS_RESOLVERS` must name the cluster DNS Service (`kube-dns.kube-system.svc.cluster.local`), never a pod IP. The chart default is correct.
