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

```bash
DB=db-postgresql-atl1-25905
doctl databases db create   "$DB" civicvault
doctl databases user create "$DB" civicvault            # prints the password
# Allow the cluster's nodes to reach the DB (add k8s cluster as a trusted source):
doctl databases firewalls append "$DB" --rule k8s:c3d2cdbc-e377-4ef8-9a39-82062e4b69c3
# Connection details (host, port 25060, sslmode=require):
doctl databases connection "$DB" --format Host,Port,User,Database
```

Assemble `DATABASE_URL`:
`postgres://civicvault:<password>@<host>:25060/civicvault?sslmode=require`

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

```bash
# From repo root. Set the image tag CI built, then apply.
( cd k8s && kustomize edit set image ghcr.io/civicpulse/civicvault=ghcr.io/civicpulse/civicvault:sha-<sha> )
kubectl apply -k k8s/
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
