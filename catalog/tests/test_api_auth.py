import pytest
from django.contrib.auth.models import AnonymousUser
from rest_framework import exceptions
from rest_framework.test import APIRequestFactory

from catalog.api.auth import BearerTokenAuthentication, HasValidIngestToken

TOKEN = "s3cret-ingest-token"


def _request(header=None):
    factory = APIRequestFactory()
    kwargs = {"HTTP_AUTHORIZATION": header} if header else {}
    return factory.post("/api/v1/meetings", **kwargs)


def test_valid_token_authenticates(settings):
    settings.INGEST_API_TOKEN = TOKEN
    user, auth = BearerTokenAuthentication().authenticate(_request(f"Bearer {TOKEN}"))
    assert isinstance(user, AnonymousUser)
    assert auth == TOKEN


def test_no_header_returns_none(settings):
    settings.INGEST_API_TOKEN = TOKEN
    assert BearerTokenAuthentication().authenticate(_request()) is None


def test_wrong_token_raises(settings):
    settings.INGEST_API_TOKEN = TOKEN
    with pytest.raises(exceptions.AuthenticationFailed):
        BearerTokenAuthentication().authenticate(_request("Bearer nope"))


def test_unconfigured_token_denies(settings):
    settings.INGEST_API_TOKEN = ""
    with pytest.raises(exceptions.AuthenticationFailed):
        BearerTokenAuthentication().authenticate(_request("Bearer anything"))


def test_authenticate_header_present():
    assert BearerTokenAuthentication().authenticate_header(_request()) == "Bearer"


def test_permission_checks_request_auth():
    perm = HasValidIngestToken()

    class _Req:
        auth = None

    assert perm.has_permission(_Req(), view=None) is False
    _Req.auth = TOKEN
    assert perm.has_permission(_Req(), view=None) is True


def test_malformed_header_raises(settings):
    settings.INGEST_API_TOKEN = TOKEN
    with pytest.raises(exceptions.AuthenticationFailed):
        BearerTokenAuthentication().authenticate(_request("Bearer"))
    with pytest.raises(exceptions.AuthenticationFailed):
        BearerTokenAuthentication().authenticate(_request("Bearer a b"))


def test_lowercase_scheme_authenticates(settings):
    settings.INGEST_API_TOKEN = TOKEN
    user, auth = BearerTokenAuthentication().authenticate(_request(f"bearer {TOKEN}"))
    assert auth == TOKEN
