"""Routes for the remote ingest API (mounted at /api/v1/)."""

from django.urls import path

from catalog.api.views import UploadsView

urlpatterns = [
    path("uploads", UploadsView.as_view(), name="api-uploads"),
]
