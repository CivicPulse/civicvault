# Deploying CivicVault to `hatchcluster`

Target cluster: DigitalOcean **hatchcluster** (atl1), Traefik + cloudflared tunnel.
Public hostname: **https://vault.civpulse.org**

The manifests here cover the in-cluster resources. Three things are applied
**out-of-band** because they touch shared/external infra or secrets:

1. A `civicvault` database + role on the managed Postgres.
2. The `civicvault-secrets` Secret (real values, never committed).
3. The Cloudflare DNS record + cloudflared tunnel route.

## Prerequisites (verified)

- `kubectl` context `do-atl1-hatchcluster`, `doctl` authenticated.
- Image published to `ghcr.io/civicpulse/civicvault:sha-<sha>` (see CI).

## 1. Provision the database (managed Postgres `db-postgresql-atl1-25905`)

`doctl` database subcommands take the cluster **ID**, not the name.

```bash
DBID=0025a591-b2ae-40c3-81c0-c4cabae3503a   # db-postgresql-atl1-25905
doctl databases db create   "$DBID" civicvault
doctl databases user create "$DBID" civicvault          # creates the user
doctl databases user get    "$DBID" civicvault --format Name,Password   # reveal password
doctl databases connection  "$DBID" --format Host,Port  # host, port 25060
```

> ⚠️ **Do NOT touch the firewall / trusted sources.** This instance is shared by
> several apps and its trusted-sources list is intentionally empty (= accept
> from anywhere, auth + SSL still required). Adding a trusted source would flip
> it to allowlist-only and cut off every other app. The cluster already has
> connectivity.

Then, as `doadmin`, grant ownership so Django can migrate and pre-create the
extensions (only `doadmin` may create them; the migration's
`CREATE EXTENSION IF NOT EXISTS` then becomes a no-op):

```bash
ADMIN_URI=$(doctl databases connection "$DBID" --format URI --no-header)
psql "$(echo "$ADMIN_URI" | sed 's#/defaultdb?#/civicvault?#')" <<'SQL'
GRANT civicvault TO doadmin;
ALTER DATABASE civicvault OWNER TO civicvault;
ALTER SCHEMA public OWNER TO civicvault;
GRANT ALL ON SCHEMA public TO civicvault;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
SQL
```

Assemble `DATABASE_URL`:
`postgres://civicvault:<password>@<host>:25060/civicvault?sslmode=require`

Apply migrations (offline workflow — run locally against the managed DB):

```bash
DATABASE_URL='postgres://civicvault:<password>@<host>:25060/civicvault?sslmode=require' \
  DEBUG=False uv run python manage.py migrate --noinput
```

## 2. Create the Secret (real values — do NOT commit)

See `secret.example.yaml` for the full `kubectl create secret generic` command.
Minimum: `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`,
`DATABASE_URL`. Add the `R2_*` keys when the media bucket is ready (until then,
leave `R2_BUCKET` empty → filesystem fallback).

```bash
kubectl create namespace civicvault --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic civicvault-secrets -n civicvault \
  --from-literal=SECRET_KEY="$(uv run python -c 'from django.core.management.utils import get_random_secret_key as k; print(k())')" \
  --from-literal=DEBUG=False \
  --from-literal=ALLOWED_HOSTS=vault.civpulse.org \
  --from-literal=CSRF_TRUSTED_ORIGINS=https://vault.civpulse.org \
  --from-literal=DATABASE_URL='postgres://civicvault:<password>@<host>:25060/civicvault?sslmode=require'
```

## 3. Deploy the app

The image package must be **public** for the cluster to pull it (the manifests
use no imagePullSecret). New GHCR packages default to private — flip it once at
`https://github.com/orgs/CivicPulse/packages/container/civicvault/settings`
(Danger Zone → Change visibility → Public). This is UI-only; there's no REST
endpoint for it.

```bash
# Pin the image tag and apply. If the standalone `kustomize` binary isn't
# installed (only kubectl's built-in kustomize is), pin via sed instead:
SHA=sha-<sha>
sed "s#civicvault:latest#civicvault:${SHA}#g" k8s/deployment.yaml | kubectl apply -f -
kubectl apply -f k8s/namespace.yaml -f k8s/serviceaccount.yaml -f k8s/service.yaml -f k8s/ingressroute.yaml
kubectl rollout status deploy/civicvault -n civicvault
```

## 4. Wire the tunnel + DNS (Cloudflare)

The tunnel (`ef29b3d0-2930-4c6b-85d6-4d8d054a3ba3`) does not yet route
`civpulse.org`. Two steps:

**a. cloudflared ingress** — add a rule above the catch-all 404 in the
`cloudflared-config` ConfigMap (`cloudflared` namespace):

```yaml
  - hostname: "vault.civpulse.org"
    service: http://traefik.traefik.svc.cluster.local:80
```

```bash
kubectl edit configmap cloudflared-config -n cloudflared    # add the rule
kubectl rollout restart deployment/cloudflared -n cloudflared
```

**b. Cloudflare DNS** — in the `civpulse.org` zone, add a proxied CNAME:

```
vault  CNAME  ef29b3d0-2930-4c6b-85d6-4d8d054a3ba3.cfargotunnel.com   (proxied)
```

(Or `cloudflared tunnel route dns ef29b3d0-… vault.civpulse.org`.)

## 5. Verify

```bash
kubectl get pods -n civicvault -w
kubectl logs deploy/civicvault -n civicvault
curl -fsS https://vault.civpulse.org/healthz/      # {"status": "ok"}
```

## Notes

- **Scaling > 1 replica:** move the `migrate` initContainer to a pre-deploy Job
  to avoid concurrent migrations.
- **Data ingestion** stays offline: run `manage.py ingest_*` / `build_relationships`
  locally with `DATABASE_URL` pointed at the managed DB.
- **Admin user:** `kubectl exec deploy/civicvault -n civicvault -it -- python manage.py createsuperuser`.
