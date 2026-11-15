import pytest
import requests_mock
from src.api_clients import DataForSEOClient, MozClient

def test_dataforseo_get_relevant_pages():
    client = DataForSEOClient()
    with requests_mock.Mocker() as m:
        m.post("https://api.dataforseo.com/v3/dataforseo_labs/google/ranked_keywords/live",
               json={
                   "tasks": [{
                       "result": [{
                           "items": [
                               {
                                   "keyword": "anxiety", 
                                   "ranked_serp_element": {
                                       "serp_item": {
                                           "url": "https://example.com/page1",
                                           "rank_absolute": 5,
                                           "etv": 100
                                       }
                                   }
                               }
                           ]
                       }]
                   }]
               })
        
        results = client.get_relevant_pages("example.com")
        assert len(results) == 1
        assert results[0]['url'] == "https://example.com/page1"
        assert results[0]['keyword_data']['keyword'] == "anxiety"

def test_moz_get_url_metrics():
    client = MozClient()
    with requests_mock.Mocker() as m:
        m.post("https://api.moz.com/v2/url_metrics",
               json={
                   "results": [
                       {"url": "https://example.com/page1", "page_authority": 35},
                       {"url": "https://example.com/page2", "page_authority": 42}
                   ]
               })
        
        results = client.get_url_metrics(["https://example.com/page1", "https://example.com/page2"])
        assert len(results) == 2
        assert results[0]['page_authority'] == 35
        assert results[1]['page_authority'] == 42


# ── C-C-12: the external calls are hardened as a CLASS, not one at a time ─────
# Promotes docs/review_2026-11-04/probes/compete/probe_dfs_abort.py. `get_search_volume`
# had timeout + retry + backoff while its siblings had neither, so a DataForSEO 429 on
# domain 17 of 34 dropped that competitor with no trace, and a ConnectionError aborted
# the run after `create_run` had already written a row.

def test_cc12_get_relevant_pages_retries_a_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("src.api_clients.time.sleep", lambda *_a: None)
    client = DataForSEOClient()
    body = {"tasks": [{"result": [{"items": [
        {"keyword": "anxiety counselling",
         "ranked_serp_element": {"serp_item": {"url": "https://example.com/a",
                                               "rank_absolute": 4, "etv": 10}}}]}]}]}
    with requests_mock.Mocker() as m:
        route = m.post(
            "https://api.dataforseo.com/v3/dataforseo_labs/google/ranked_keywords/live",
            [{"status_code": 429}, {"json": body}])
        results = client.get_relevant_pages("example.com")
    assert route.call_count == 2
    assert len(results) == 1
    assert client.last_error is None


def test_cc12_get_relevant_pages_never_raises_and_records_the_reason(monkeypatch):
    monkeypatch.setattr("src.api_clients.time.sleep", lambda *_a: None)
    client = DataForSEOClient()
    with requests_mock.Mocker() as m:
        import requests as _requests
        m.post("https://api.dataforseo.com/v3/dataforseo_labs/google/ranked_keywords/live",
               exc=_requests.exceptions.ConnectionError)
        results = client.get_relevant_pages("example.com")   # must NOT raise
    assert results == []
    assert "ConnectionError" in client.last_error


def test_cc12_a_terminal_4xx_is_not_retried(monkeypatch):
    monkeypatch.setattr("src.api_clients.time.sleep", lambda *_a: None)
    client = DataForSEOClient()
    with requests_mock.Mocker() as m:
        route = m.post(
            "https://api.dataforseo.com/v3/dataforseo_labs/google/ranked_keywords/live",
            status_code=401)
        assert client.get_relevant_pages("example.com") == []
    assert route.call_count == 1          # retrying a 401 only burns time
    assert client.last_error == "HTTP 401"


def test_cc12_moz_url_metrics_retries_then_raises_on_a_terminal_failure(monkeypatch):
    monkeypatch.setattr("src.api_clients.time.sleep", lambda *_a: None)
    client = MozClient()
    with requests_mock.Mocker() as m:
        route = m.post("https://api.moz.com/v2/url_metrics", status_code=503)
        with pytest.raises(Exception) as excinfo:
            client.get_url_metrics(["https://example.com/a"])
    assert route.call_count == 3                  # 503 is transient → retried
    assert "503" in str(excinfo.value)


# ── C-C-11: an outage is None, an empty answer is {} ─────────────────────────

def test_cc11_get_search_volume_returns_none_when_the_provider_never_answered(monkeypatch):
    monkeypatch.setattr("src.api_clients.time.sleep", lambda *_a: None)
    client = DataForSEOClient()
    with requests_mock.Mocker() as m:
        m.post("https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live",
               status_code=429)
        assert client.get_search_volume(["acme counselling"]) is None


def test_cc11_get_search_volume_returns_a_mapping_when_it_answered():
    client = DataForSEOClient()
    with requests_mock.Mocker() as m:
        m.post("https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live",
               json={"tasks": [{"result": [{"keyword": "Acme Counselling",
                                            "search_volume": 90,
                                            "monthly_searches": []}]}]})
        got = client.get_search_volume(["Acme Counselling"])
    assert got == {"acme counselling": {"search_volume": 90, "monthly_searches": []}}


def test_cc11_an_empty_result_for_a_real_request_is_unknown_not_zero():
    """DataForSEO returns one item per keyword; an empty `result` is an anomaly, and a
    brand with no demand comes back as rows with search_volume 0. Treating the anomaly
    as a measured zero is the C-C-11 failure one level up."""
    client = DataForSEOClient()
    with requests_mock.Mocker() as m:
        m.post("https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live",
               json={"tasks": [{"result": []}]})
        assert client.get_search_volume(["acme counselling"]) is None


def test_cc11_a_zero_volume_row_is_a_measured_zero():
    client = DataForSEOClient()
    with requests_mock.Mocker() as m:
        m.post("https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live",
               json={"tasks": [{"result": [{"keyword": "acme counselling",
                                            "search_volume": 0,
                                            "monthly_searches": []}]}]})
        assert client.get_search_volume(["acme counselling"]) == {
            "acme counselling": {"search_volume": 0, "monthly_searches": []}}


def test_cc11_an_empty_keyword_list_asks_nothing_and_answers_nothing():
    assert DataForSEOClient().get_search_volume([]) == {}


# ── C-C-03 / C-C-04: a URL with no Moz record is ABSENT, never 0 ─────────────

def test_cc03_page_authority_map_omits_urls_moz_had_no_record_for():
    from src.api_clients import page_authority_map
    results = [{"url": "https://example.com/a", "page_authority": 35}]
    got = page_authority_map(results, ["https://example.com/a", "https://example.com/b"])
    assert got == {"https://example.com/a": 35.0}
    assert "https://example.com/b" not in got      # not present with 0


def test_cc04_page_authority_map_accepts_mozs_own_page_key():
    """Moz's url-metrics objects identify the target as `page`, scheme-less. Reading
    only `url` produced `{None: <PA of the last result>}` — one arbitrary figure for
    every URL. C-C-04 stays open until a live run confirms the endpoint."""
    from src.api_clients import page_authority_map
    results = [{"page": "example.com/a", "page_authority": 35},
               {"page": "example.com/b/", "pa": 42}]
    got = page_authority_map(results, ["https://example.com/a", "https://example.com/b"])
    assert got == {"https://example.com/a": 35.0, "https://example.com/b": 42.0}


def test_cc03_a_result_without_any_authority_figure_is_omitted():
    from src.api_clients import page_authority_map
    got = page_authority_map([{"url": "https://example.com/a", "page_authority": None}],
                             ["https://example.com/a"])
    assert got == {}
