"""pytest 全局 fixtures

合入上游代码后启用。
"""
import os

import django
import pytest


def pytest_configure(config):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "archery.settings")
    django.setup()


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()
