"""URL routes for the core app."""

from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("search/", views.search, name="search"),
    path("graph/", views.graph, name="graph"),
    path("documents/<int:pk>/source/", views.document_source, name="document_source"),
    path("healthz/", views.health, name="health"),
]
