"""`YouTubeDataClient` — the transport and the three endpoints.

Coverage on 2026-11-16 had this module at 63%, and the gap was the whole of
`_get`'s retry and failure handling plus all three endpoint parsers. The
uncovered paths are the ones about to run for the first time: `TODO.md`'s
resume path for SC-7-YT is "provision the free `YOUTUBE_API_KEY` and do one
live run", so until then nothing has ever exercised a real response — let alone
a 429, a quota refusal or a hidden subscriber count.

The retries sleep `1.5 * (attempt + 1)` seconds, which is why these were never
written: exercising two retries costs 4.5s of suite time. `time.sleep` is
patched out.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import requests as _requests

from src.youtube_client import (YouTubeDataClient, YouTubeError,
                                YouTubeTransientError)


class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _client(key="test-key"):
    """The real constructor reads the key from the env var named by
    `cfg.api_key_env` (default `YOUTUBE_API_KEY`) — there is no `api_key`
    argument, which is itself worth pinning: `api_key_env` is the only way in,
    and an absent variable is what makes the client unavailable."""
    env = dict(os.environ)
    if key:
        env["YOUTUBE_API_KEY"] = key
    else:
        env.pop("YOUTUBE_API_KEY", None)
    with patch.dict(os.environ, env, clear=True):
        client = YouTubeDataClient()
    client.max_retries = 3
    return client


class TestTheKeyGuard(unittest.TestCase):
    """P1.3: never build a keyless request."""

    def test_no_key_means_unavailable(self):
        self.assertFalse(_client(key="").available)

    def test_a_call_without_a_key_raises_rather_than_going_out(self):
        client = _client(key="")
        with patch("src.youtube_client.requests.get") as get:
            with self.assertRaises(YouTubeError):
                client.search_channels("jericho counselling", 3)
        get.assert_not_called()

    def test_the_key_is_sent_as_a_parameter_not_a_header(self):
        client = _client()
        with patch("src.youtube_client.requests.get",
                   return_value=_Resp(200, {"items": []})) as get:
            client.search_channels("q", 1)
        self.assertEqual(get.call_args.kwargs["params"]["key"], "test-key")


class TestTransientVersusTerminal(unittest.TestCase):
    """A quota refusal must be retried; a bad key must not be."""

    def _call(self, responses):
        client = _client()
        with patch("src.youtube_client.time.sleep"), \
             patch("src.youtube_client.requests.get", side_effect=responses) as get:
            try:
                return client.search_channels("q", 1), None, get
            except Exception as exc:  # noqa: BLE001 - the test inspects it
                return None, exc, get

    def test_a_429_is_retried_then_raises_transient(self):
        _out, error, get = self._call([_Resp(429), _Resp(429), _Resp(429)])
        self.assertIsInstance(error, YouTubeTransientError)
        self.assertEqual(get.call_count, 3)

    def test_a_500_is_retried(self):
        _out, error, get = self._call([_Resp(503), _Resp(503), _Resp(503)])
        self.assertIsInstance(error, YouTubeTransientError)
        self.assertEqual(get.call_count, 3)

    def test_a_quota_403_is_transient_not_terminal(self):
        """quotaExceeded means "come back tomorrow", not "your key is wrong"."""
        quota = _Resp(403, {"error": {"errors": [{"reason": "quotaExceeded"}]}})
        _out, error, get = self._call([quota, quota, quota])
        self.assertIsInstance(error, YouTubeTransientError)
        self.assertEqual(get.call_count, 3)

    def test_a_bad_key_403_is_terminal_and_not_retried(self):
        """Retrying a rejected key burns nothing but time, and the message must
        tell the owner which it was."""
        bad_key = _Resp(403, {"error": {"errors": [{"reason": "keyInvalid"}]}},
                        text="API key not valid")
        _out, error, get = self._call([bad_key])
        self.assertIsInstance(error, YouTubeError)
        self.assertNotIsInstance(error, YouTubeTransientError)
        self.assertEqual(get.call_count, 1)
        self.assertIn("403", str(error))

    def test_a_400_is_terminal(self):
        _out, error, get = self._call([_Resp(400, text="bad request")])
        self.assertIsInstance(error, YouTubeError)
        self.assertEqual(get.call_count, 1)

    def test_a_403_whose_body_is_not_json_is_terminal(self):
        """`_is_transient` parses the body to decide; an HTML error page must
        not be read as a quota refusal and retried forever."""
        _out, error, get = self._call([_Resp(403, None, text="<html>nope")])
        self.assertIsInstance(error, YouTubeError)
        self.assertEqual(get.call_count, 1)

    def test_a_network_error_is_retried_then_transient(self):
        error_response = _requests.exceptions.ConnectionError("reset")
        _out, error, get = self._call([error_response] * 3)
        self.assertIsInstance(error, YouTubeTransientError)
        self.assertEqual(get.call_count, 3)
        self.assertIn("network", str(error))

    def test_a_retry_that_then_succeeds_returns_the_payload(self):
        client = _client()
        with patch("src.youtube_client.time.sleep"), \
             patch("src.youtube_client.requests.get",
                   side_effect=[_Resp(429),
                                _Resp(200, {"items": [
                                    {"id": {"channelId": "UC1"},
                                     "snippet": {"title": "Jericho"}}]})]):
            out = client.search_channels("q", 1)
        self.assertEqual(out[0]["channel_id"], "UC1")

    def test_a_200_with_an_unparseable_body_raises_rather_than_silently_empty(self):
        """`resp.json()` raising on a 200 would otherwise propagate a ValueError
        from inside the transport, which the caller does not expect."""
        client = _client()
        with patch("src.youtube_client.time.sleep"), \
             patch("src.youtube_client.requests.get", return_value=_Resp(200, None)):
            with self.assertRaises(ValueError):
                client.search_channels("q", 1)


class TestSearchChannels(unittest.TestCase):

    def _search(self, payload):
        client = _client()
        with patch("src.youtube_client.requests.get",
                   return_value=_Resp(200, payload)):
            return client.search_channels("jericho counselling", 3)

    def test_the_channel_id_is_read_from_either_place(self):
        out = self._search({"items": [
            {"id": {"channelId": "UC_from_id"}, "snippet": {"title": "A"}},
            {"id": {}, "snippet": {"channelId": "UC_from_snippet", "title": "B"}},
        ]})
        self.assertEqual([c["channel_id"] for c in out],
                         ["UC_from_id", "UC_from_snippet"])

    def test_an_item_with_no_channel_id_is_dropped_not_kept_blank(self):
        out = self._search({"items": [{"snippet": {"title": "No id"}}]})
        self.assertEqual(out, [])

    def test_an_empty_result_is_an_empty_list(self):
        self.assertEqual(self._search({"items": []}), [])
        self.assertEqual(self._search({}), [])
        self.assertEqual(self._search({"items": None}), [])


class TestGetChannels(unittest.TestCase):

    PAYLOAD = {"items": [{
        "id": "UC123",
        "snippet": {"title": "Jericho Counselling", "customUrl": "@jerichoc",
                    "description": "We help"},
        "statistics": {"subscriberCount": "1234", "videoCount": "42"},
        "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}},
    }]}

    def _get(self, payload, **kwargs):
        client = _client()
        with patch("src.youtube_client.requests.get",
                   return_value=_Resp(200, payload)) as get:
            return client.get_channels(**kwargs), get

    def test_a_channel_is_parsed(self):
        channel, _get = self._get(self.PAYLOAD, channel_id="UC123")
        self.assertEqual(channel["channel_id"], "UC123")
        self.assertEqual(channel["subscriber_count"], 1234)
        self.assertEqual(channel["video_count"], 42)
        self.assertEqual(channel["uploads_playlist_id"], "UU123")
        self.assertEqual(channel["custom_url"], "@jerichoc")

    def test_a_handle_is_sent_without_its_at_sign(self):
        _channel, get = self._get(self.PAYLOAD, handle="@jerichoc")
        self.assertEqual(get.call_args.kwargs["params"]["forHandle"], "jerichoc")

    def test_neither_id_nor_handle_makes_no_request_at_all(self):
        client = _client()
        with patch("src.youtube_client.requests.get") as get:
            self.assertIsNone(client.get_channels())
        get.assert_not_called()

    def test_an_absent_channel_is_none_not_an_empty_dict(self):
        """None means "no such channel"; an empty dict would read as a channel
        with no subscribers."""
        channel, _get = self._get({"items": []}, channel_id="UC404")
        self.assertIsNone(channel)

    def test_a_hidden_subscriber_count_is_flagged(self):
        payload = {"items": [{
            "id": "UC1", "snippet": {}, "contentDetails": {},
            "statistics": {"hiddenSubscriberCount": True, "videoCount": "3"},
        }]}
        channel, _get = self._get(payload, channel_id="UC1")
        self.assertTrue(channel["hidden_subscriber_count"])
        # …and the count itself is None, not 0: hidden is not zero.
        self.assertIsNone(channel["subscriber_count"])

    def test_a_non_numeric_count_is_none_rather_than_zero(self):
        payload = {"items": [{
            "id": "UC1", "snippet": {}, "contentDetails": {},
            "statistics": {"subscriberCount": "lots"},
        }]}
        channel, _get = self._get(payload, channel_id="UC1")
        self.assertIsNone(channel["subscriber_count"])

    def test_a_channel_with_no_uploads_playlist_is_handled(self):
        payload = {"items": [{"id": "UC1", "snippet": {}, "statistics": {},
                              "contentDetails": {}}]}
        channel, _get = self._get(payload, channel_id="UC1")
        self.assertIsNone(channel["uploads_playlist_id"])


class TestGetRecentUploads(unittest.TestCase):

    def _uploads(self, payload, playlist="UU123"):
        client = _client()
        with patch("src.youtube_client.requests.get",
                   return_value=_Resp(200, payload)) as get:
            return client.get_recent_uploads(playlist), get

    def test_dates_come_from_either_field(self):
        dates, _get = self._uploads({"items": [
            {"contentDetails": {"videoPublishedAt": "2026-10-01T00:00:00Z"}},
            {"snippet": {"publishedAt": "2026-09-01T00:00:00Z"}},
        ]})
        self.assertEqual(dates, ["2026-10-01T00:00:00Z", "2026-09-01T00:00:00Z"])

    def test_an_item_with_no_date_is_dropped(self):
        dates, _get = self._uploads({"items": [{"snippet": {}}]})
        self.assertEqual(dates, [])

    def test_no_playlist_id_makes_no_request(self):
        client = _client()
        with patch("src.youtube_client.requests.get") as get:
            self.assertEqual(client.get_recent_uploads(""), [])
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
