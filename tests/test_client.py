"""Unit tests for AppleMusicClient in client.py."""

import base64
import json
import time
import unittest
from unittest.mock import MagicMock, mock_open, patch

from client import AppleMusicClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jwt(exp: int) -> str:
    """Build a minimal JWT-like string with the given expiry timestamp."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload_bytes = json.dumps({"exp": exp}).encode()
    payload = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesig"


def _make_client(bearer_token="test-token", user_token=None):
    """Return an AppleMusicClient with _get_bearer_token short-circuited."""
    with patch.object(AppleMusicClient, "_get_bearer_token", return_value=bearer_token):
        return AppleMusicClient(user_token=user_token)


# ---------------------------------------------------------------------------
# _is_jwt_expired
# ---------------------------------------------------------------------------

class TestIsJwtExpired(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def test_valid_token_returns_false(self):
        future_exp = int(time.time()) + 3600
        token = _make_jwt(future_exp)
        self.assertFalse(self.client._is_jwt_expired(token))

    def test_expired_token_returns_true(self):
        past_exp = int(time.time()) - 3600
        token = _make_jwt(past_exp)
        self.assertTrue(self.client._is_jwt_expired(token))

    def test_malformed_token_returns_true(self):
        self.assertTrue(self.client._is_jwt_expired("not.a.jwt"))

    def test_empty_string_returns_true(self):
        self.assertTrue(self.client._is_jwt_expired(""))

    def test_missing_exp_field_returns_true(self):
        header = base64.urlsafe_b64encode(b'{}').rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(b'{}').rstrip(b"=").decode()
        token = f"{header}.{payload}.sig"
        # exp defaults to 0 → expired
        self.assertTrue(self.client._is_jwt_expired(token))


# ---------------------------------------------------------------------------
# _fetch_new_bearer_token
# ---------------------------------------------------------------------------

class TestFetchNewBearerToken(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def _urlopen_side_effect(self, html_response, js_response):
        """Return a side-effect function that yields two mock responses."""
        responses = [
            MagicMock(**{"read.return_value": html_response.encode(), "__enter__": lambda s: s, "__exit__": MagicMock(return_value=False)}),
            MagicMock(**{"read.return_value": js_response.encode(), "__enter__": lambda s: s, "__exit__": MagicMock(return_value=False)}),
        ]
        return iter(responses)

    @patch("urllib.request.urlopen")
    def test_extracts_token_from_js(self, mock_urlopen):
        fake_token = "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0In0.fakesig"
        html = '<script src="/assets/index-abc.js"></script>'
        js = f'var t="{fake_token}"'

        mock_urlopen.side_effect = self._urlopen_side_effect(html, js)
        result = self.client._fetch_new_bearer_token()
        self.assertEqual(result, fake_token)

    @patch("urllib.request.urlopen")
    def test_returns_none_when_no_script_tag(self, mock_urlopen):
        html = "<html><body>no script here</body></html>"
        mock_urlopen.return_value = MagicMock(read=MagicMock(return_value=html.encode()))
        result = self.client._fetch_new_bearer_token()
        self.assertIsNone(result)

    @patch("urllib.request.urlopen", side_effect=Exception("network error"))
    def test_returns_none_on_network_error(self, _mock):
        result = self.client._fetch_new_bearer_token()
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# _get_bearer_token
# ---------------------------------------------------------------------------

class TestGetBearerToken(unittest.TestCase):

    def _make_uncached_client(self):
        """Create client without patching _get_bearer_token (for integration-style tests)."""
        return AppleMusicClient.__new__(AppleMusicClient)

    def test_returns_cached_valid_token(self):
        client = self._make_uncached_client()
        future_exp = int(time.time()) + 3600
        cached_token = _make_jwt(future_exp)

        m = mock_open(read_data=cached_token)
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", m):
            token = client._get_bearer_token()

        self.assertEqual(token, cached_token)

    def test_fetches_new_token_when_cache_expired(self):
        client = self._make_uncached_client()
        past_exp = int(time.time()) - 3600
        expired_token = _make_jwt(past_exp)
        fresh_token = "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJuZXcifQ.newsig"

        m = mock_open(read_data=expired_token)
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", m), \
             patch.object(AppleMusicClient, "_fetch_new_bearer_token", return_value=fresh_token):
            token = client._get_bearer_token()

        self.assertEqual(token, fresh_token)

    def test_fetches_new_token_when_no_file(self):
        client = self._make_uncached_client()
        fresh_token = "brandnewtoken"

        m = mock_open()
        with patch("os.path.exists", return_value=False), \
             patch("builtins.open", m), \
             patch.object(AppleMusicClient, "_fetch_new_bearer_token", return_value=fresh_token):
            token = client._get_bearer_token()

        self.assertEqual(token, fresh_token)

    def test_returns_none_when_fetch_fails(self):
        client = self._make_uncached_client()

        with patch("os.path.exists", return_value=False), \
             patch.object(AppleMusicClient, "_fetch_new_bearer_token", return_value=None):
            token = client._get_bearer_token()

        self.assertIsNone(token)


# ---------------------------------------------------------------------------
# get_room_new_releases
# ---------------------------------------------------------------------------

ROOM_HTML_TEMPLATE = """
<script type="application/json" id="serialized-server-data">{payload}</script>
"""


def _make_room_payload(sections):
    data = [{"data": {"data": [{"data": {"sections": sections}}]}}]
    return json.dumps(data)


class TestGetRoomNewReleases(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def _mock_response(self, html: str):
        mock_resp = MagicMock()
        mock_resp.read.return_value = html.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    @patch("urllib.request.urlopen")
    def test_extracts_releases_from_new_releases_section(self, mock_urlopen):
        sections = [
            {
                "header": "New in Music",
                "items": [
                    {
                        "item": {
                            "attributes": {
                                "title": "Test Album",
                                "artistName": "Test Artist",
                                "url": "https://music.apple.com/us/album/test/123456789",
                            }
                        }
                    }
                ],
            }
        ]
        payload = _make_room_payload(sections)
        html = ROOM_HTML_TEMPLATE.format(payload=payload)
        mock_urlopen.return_value = self._mock_response(html)

        releases = self.client.get_room_new_releases("https://example.com", "us")

        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]["title"], "Test Album")
        self.assertEqual(releases[0]["storeAdamID"], "123456789")
        self.assertEqual(releases[0]["storefronts"], ["us"])

    @patch("urllib.request.urlopen")
    def test_ignores_non_new_release_sections(self, mock_urlopen):
        sections = [
            {
                "header": "Featured Playlists",
                "items": [
                    {"item": {"attributes": {"title": "Chill Hits", "artistName": "Various", "url": "https://music.apple.com/us/playlist/test/999"}}}
                ],
            }
        ]
        payload = _make_room_payload(sections)
        html = ROOM_HTML_TEMPLATE.format(payload=payload)
        mock_urlopen.return_value = self._mock_response(html)

        releases = self.client.get_room_new_releases("https://example.com", "us")
        self.assertEqual(releases, [])

    @patch("urllib.request.urlopen")
    def test_returns_empty_list_when_no_script_tag(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response("<html>no data</html>")
        releases = self.client.get_room_new_releases("https://example.com", "us")
        self.assertEqual(releases, [])

    @patch("urllib.request.urlopen", side_effect=Exception("network error"))
    def test_returns_empty_list_on_exception(self, _):
        releases = self.client.get_room_new_releases("https://example.com", "us")
        self.assertEqual(releases, [])


# ---------------------------------------------------------------------------
# get_artist_new_releases
# ---------------------------------------------------------------------------

class TestGetArtistNewReleases(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def _mock_response(self, html: str):
        mock_resp = MagicMock()
        mock_resp.read.return_value = html.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def _make_artist_payload(self, sections):
        data = [{"data": {"data": [{"data": {"sections": sections}}]}}]
        return json.dumps(data)

    @patch("urllib.request.urlopen")
    def test_extracts_album_section(self, mock_urlopen):
        sections = [
            {
                "header": "Albums",
                "items": [
                    {
                        "item": {
                            "attributes": {
                                "title": "Great Album",
                                "artistName": "Great Artist",
                                "url": "https://music.apple.com/us/album/great/111222333",
                            }
                        }
                    }
                ],
            }
        ]
        payload = self._make_artist_payload(sections)
        html = ROOM_HTML_TEMPLATE.format(payload=payload)
        mock_urlopen.return_value = self._mock_response(html)

        releases = self.client.get_artist_new_releases("https://example.com", "us")
        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0]["title"], "Great Album")
        self.assertEqual(releases[0]["storeAdamID"], "111222333")

    @patch("urllib.request.urlopen")
    def test_deduplicates_releases(self, mock_urlopen):
        item = {
            "item": {
                "attributes": {
                    "title": "Dup Album",
                    "artistName": "Artist",
                    "url": "https://music.apple.com/us/album/dup/777888999",
                }
            }
        }
        sections = [
            {"header": "Latest Release", "items": [item]},
            {"header": "Albums", "items": [item]},
        ]
        payload = self._make_artist_payload(sections)
        html = ROOM_HTML_TEMPLATE.format(payload=payload)
        mock_urlopen.return_value = self._mock_response(html)

        releases = self.client.get_artist_new_releases("https://example.com", "us")
        ids = [r["storeAdamID"] for r in releases]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate storeAdamIDs found")

    @patch("urllib.request.urlopen")
    def test_returns_empty_list_when_no_allowed_section(self, mock_urlopen):
        sections = [{"header": "Music Videos", "items": []}]
        payload = self._make_artist_payload(sections)
        html = ROOM_HTML_TEMPLATE.format(payload=payload)
        mock_urlopen.return_value = self._mock_response(html)

        releases = self.client.get_artist_new_releases("https://example.com", "us")
        self.assertEqual(releases, [])

    @patch("urllib.request.urlopen", side_effect=Exception("network error"))
    def test_returns_empty_list_on_exception(self, _):
        releases = self.client.get_artist_new_releases("https://example.com", "us")
        self.assertEqual(releases, [])


# ---------------------------------------------------------------------------
# get_album_release_date
# ---------------------------------------------------------------------------

def _make_album_html(description: str) -> str:
    data = [{"data": {"description": description}}]
    payload = json.dumps(data)
    return ROOM_HTML_TEMPLATE.format(payload=payload)


class TestGetAlbumReleaseDate(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    def _mock_response(self, html: str):
        mock_resp = MagicMock()
        mock_resp.read.return_value = html.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    @patch("urllib.request.urlopen")
    def test_parses_japanese_date_format(self, mock_urlopen):
        html = _make_album_html("このアルバムは2026年3月12日にリリースされました。10曲収録。")
        mock_urlopen.return_value = self._mock_response(html)
        result = self.client.get_album_release_date("https://example.com")
        self.assertEqual(result, "2026-03-12")

    @patch("urllib.request.urlopen")
    def test_parses_day_month_year_format(self, mock_urlopen):
        html = _make_album_html("Released on 5 March 2026, featuring 12 Songs.")
        mock_urlopen.return_value = self._mock_response(html)
        result = self.client.get_album_release_date("https://example.com")
        self.assertEqual(result, "2026-03-05")

    @patch("urllib.request.urlopen")
    def test_parses_month_day_year_format(self, mock_urlopen):
        html = _make_album_html("Available from March 5, 2026. Contains 8 Songs.")
        mock_urlopen.return_value = self._mock_response(html)
        result = self.client.get_album_release_date("https://example.com")
        self.assertEqual(result, "2026-03-05")

    @patch("urllib.request.urlopen")
    def test_fallback_to_year_only(self, mock_urlopen):
        # Description has year but no full date format
        html = _make_album_html("Great album from 2025 with 5 Songs.")
        mock_urlopen.return_value = self._mock_response(html)
        result = self.client.get_album_release_date("https://example.com")
        self.assertIn("2025", result)

    @patch("urllib.request.urlopen")
    def test_returns_unknown_when_no_description(self, mock_urlopen):
        data = [{"data": {}}]
        payload = json.dumps(data)
        html = ROOM_HTML_TEMPLATE.format(payload=payload)
        mock_urlopen.return_value = self._mock_response(html)
        result = self.client.get_album_release_date("https://example.com")
        self.assertEqual(result, "Unknown")

    @patch("urllib.request.urlopen")
    def test_returns_unknown_when_no_script_tag(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response("<html>nothing</html>")
        result = self.client.get_album_release_date("https://example.com")
        self.assertEqual(result, "Unknown")

    @patch("urllib.request.urlopen", side_effect=Exception("network error"))
    def test_returns_unknown_on_exception(self, _):
        result = self.client.get_album_release_date("https://example.com")
        self.assertEqual(result, "Unknown")



# ---------------------------------------------------------------------------
# check_storefront_availability
# ---------------------------------------------------------------------------

class TestCheckStorefrontAvailability(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()

    @patch("urllib.request.urlopen")
    def test_all_available(self, mock_urlopen):
        mock_urlopen.return_value = MagicMock()
        result = self.client.check_storefront_availability("123", ["us", "jp"])
        self.assertEqual(result["available"], ["us", "jp"])
        self.assertEqual(result["unavailable"], [])

    @patch("urllib.request.urlopen")
    def test_some_unavailable(self, mock_urlopen):
        def side_effect(req, timeout=5):
            if "/jp/" in req.full_url:
                raise Exception("Not Found")
            return MagicMock()
            
        mock_urlopen.side_effect = side_effect
        result = self.client.check_storefront_availability("123", ["us", "jp"])
        self.assertEqual(result["available"], ["us"])
        self.assertEqual(result["unavailable"], ["jp"])


if __name__ == "__main__":
    unittest.main()
