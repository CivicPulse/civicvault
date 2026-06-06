"""Single-token bearer authentication for the remote ingest API.

No user table: the token is a shared secret in settings.INGEST_API_TOKEN.
When the token is unset the authenticator denies everything — never an
accidental open door. Comparison is timing-safe.
"""

from django.contrib.auth.models import AnonymousUser
from django.utils.crypto import constant_time_compare
from rest_framework import authentication, exceptions, permissions


class BearerTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("latin-1")
        if not header:
            return None  # no credentials → let the permission return 401
        parts = header.split()
        if parts[0] != self.keyword:
            return None  # a different scheme; not ours to judge
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Invalid bearer header.")
        configured = settings_token()
        if not configured:
            raise exceptions.AuthenticationFailed("Ingest API token not configured.")
        if not constant_time_compare(parts[1], configured):
            raise exceptions.AuthenticationFailed("Invalid token.")
        return (AnonymousUser(), parts[1])

    def authenticate_header(self, request):
        # Returning a value makes DRF render auth failures as 401 (not 403).
        return self.keyword


def settings_token():
    from django.conf import settings

    return settings.INGEST_API_TOKEN


class HasValidIngestToken(permissions.BasePermission):
    message = "A valid ingest token is required."

    def has_permission(self, request, view):
        return bool(request.auth)
