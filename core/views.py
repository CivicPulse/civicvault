"""Core views for CivicVault.

`home` is the public landing placeholder. `health` is a machine-readable
liveness/readiness endpoint intended for load balancers, K8s probes, and uptime
checks (see project_brief.md §12 step 1).
"""

from django.http import JsonResponse
from django.shortcuts import render


def home(request):
    """Render the public hello-world landing page."""
    return render(request, "core/home.html")


def health(request):
    """Report service health as JSON.

    TODO(you): decide what "healthy" means for CivicVault and implement the check.

    Design decision worth your input — this is a liveness vs. readiness call:
      - A *liveness* check just confirms the process is up (always return ok).
      - A *readiness* check confirms the app can actually serve requests, which
        for us means the database is reachable (CivicVault is useless without
        Postgres). For that, add `from django.db import connection` up top.

    Suggested shape (5-10 lines): try a trivial DB query
    (`connection.ensure_connection()` or `SELECT 1` via `connection.cursor()`),
    return JsonResponse({"status": "ok"}) on success, and on failure return
    JsonResponse({"status": "error", "detail": "<reason>"}, status=503).

    Consider: do you want the endpoint to fail (503) when the DB is down so K8s
    pulls the pod from rotation, or stay 200 so a transient DB blip doesn't kill
    every replica at once? That trade-off is yours to make.
    """
    # Placeholder so the site runs today; replace with your chosen check.
    return JsonResponse({"status": "ok"})
