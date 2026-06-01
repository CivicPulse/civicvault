def test_truth():
    assert True


def test_settings_import():
    from django.conf import settings

    assert settings.INSTALLED_APPS  # settings module loads under pytest-django
