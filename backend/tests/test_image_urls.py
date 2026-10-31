"""Hermetic image signing/cache regression tests (no DB or Azure connection)."""
import base64
import json
from datetime import datetime, timezone
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from app.services import storage as module
from app.services.storage import StorageService


@pytest.fixture
def storage():
    service = StorageService.__new__(StorageService)
    service.storage_backend = "azure"
    service._azure_container_name = "images"
    service._azure_connection_string = "AccountKey=" + base64.b64encode(b"test-secret").decode()
    service._blob_service_client = Mock(account_name="testaccount")
    service._container_client = Mock()
    service._container_client.get_blob_client.side_effect = lambda path: Mock(
        url=f"https://testaccount.blob.core.windows.net/images/{path}",
        get_blob_properties=Mock(side_effect=AssertionError("Signing must never make a network call")),
    )
    return service


def freeze(monkeypatch, hour, minute):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 31, hour, minute, tzinfo=timezone.utc)
    monkeypatch.setattr(module, "datetime", Clock)


def test_sas_stable_within_bucket_and_rotates(monkeypatch, storage):
    freeze(monkeypatch, 10, 1)
    first = storage._generate_sas_url("thumbnails/a_400.png")
    freeze(monkeypatch, 10, 59)
    assert storage._generate_sas_url("thumbnails/a_400.png") == first
    query = parse_qs(urlsplit(first).query)
    assert query['sp'] == ['r']
    assert query['se'] == ['2026-10-31T12:00:00Z']
    assert query['rscc'] == ['private, max-age=3300, immutable']
    assert query['sig']
    freeze(monkeypatch, 11, 0)
    assert storage._generate_sas_url("thumbnails/a_400.png") != first


def test_covers_are_mutable_and_short_cached(storage):
    query = parse_qs(urlsplit(storage.generate_folder_cover_sas_url("azure://images/folder_covers/folder_2.jpg")).query)
    assert query['rscc'] == ['private, max-age=300']
    assert 'immutable' not in query['rscc'][0]


@pytest.mark.parametrize('download', [False, True])
def test_redirect_and_resolution(storage, download):
    method = storage.get_file_response_with_filename if download else storage.get_file_response
    response = method('images', 'a.png')
    assert response.status_code == 302
    assert response.headers['cache-control'] == 'private, max-age=300'
    resolved = method('images', 'a.png', resolve=True)
    assert resolved.headers['cache-control'] == 'private, no-store'
    assert json.loads(resolved.body)['url'] == response.headers['location']


def test_local_resolution_and_missing_files(tmp_path, storage):
    storage.storage_backend = 'local'
    storage.local_path = tmp_path
    assert storage.get_file_response('images', 'missing.png', resolve=True) is None
    (tmp_path / 'images').mkdir()
    (tmp_path / 'images/a.png').write_bytes(b'image')
    assert json.loads(storage.get_file_response('images', 'a.png', resolve=True).body) == {'url': None}


def test_image_response_includes_direct_urls(monkeypatch, storage):
    from app.schemas import ImageResponse

    monkeypatch.setattr(module, 'get_storage_service', lambda: storage)
    response = ImageResponse.model_construct(
        object_key='a.png', thumbnail_uri_medium='azure://images/thumbnails/a_400.png',
        thumbnail_uri_small=None, thumbnail_uri_large="azure://images/thumbnails/a_800.png",
    )
    assert urlsplit(response.thumbnail_url).path == '/images/thumbnails/a_400.png'
    assert set(response.thumbnail_urls) == {'400', '800'}
    assert urlsplit(response.thumbnail_urls['800']).path == '/images/thumbnails/a_800.png'
    assert urlsplit(response.image_url).path == '/images/images/a.png'


def test_file_auth_accepts_fresh_bearer_over_stale_query():
    from fastapi.security import HTTPAuthorizationCredentials

    from app.core.security import create_access_token, get_current_user_from_token_param

    db = Mock()
    user = Mock(is_active=True)
    db.query.return_value.filter.return_value.first.return_value = user
    credentials = HTTPAuthorizationCredentials(scheme='Bearer', credentials=create_access_token(7, 'test@example.com'))
    assert get_current_user_from_token_param(token='expired', credentials=credentials, db=db) is user
