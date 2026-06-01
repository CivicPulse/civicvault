"""Core views for CivicVault.

`home` is the public landing placeholder. `health` is a machine-readable
liveness endpoint intended for load balancers, K8s probes, and uptime checks
(see project_brief.md §12 step 1).
"""

from django.http import JsonResponse
from django.shortcuts import render


def home(request):
    """Render the public hello-world landing page."""
    return render(request, "core/home.html")


def health(request):
    """Liveness check: report that the process is up and serving requests.

    This deliberately does NOT touch the database. A liveness probe answers only
    "is this process alive?" — if it returns, the WSGI worker accepted a request
    and ran Python, which is all liveness needs to know. Keeping the database out
    of it means a transient Postgres blip can't make K8s restart otherwise-healthy
    pods (a DB-coupled liveness probe can cause a restart storm under DB pressure).

    Upgrade path: when we want a *readiness* probe (gate traffic on the DB being
    reachable), add a separate endpoint that runs a trivial query and returns 503
    on failure — readiness, not liveness, is the right place for that check.
    """
    return JsonResponse({"status": "ok"})
