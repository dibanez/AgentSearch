"""Tests for the retries on transient OpenAI API errors."""

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from shopping_agent import agent, db, web


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/responses")


def _http_error(code: int) -> APIStatusError:
    response = httpx.Response(code, request=_request())
    cls = RateLimitError if code == 429 else APIStatusError
    return cls(f"error {code}", response=response, body=None)


class _FakeClient:
    """Client that fails the first `failures` times and then responds."""

    def __init__(self, error: Exception, failures: int):
        self.error, self.failures, self.calls = error, failures, 0
        self.responses = self

    def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error
        return "response"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Retries do not really sleep during the tests."""
    monkeypatch.setattr(agent.time, "sleep", lambda _s: None)


# --- error classification -----------------------------------------------------

def test_openai_5xx_errors_are_transient():
    assert agent._is_transient(_http_error(500))
    assert agent._is_transient(_http_error(503))


def test_rate_limit_and_network_errors_are_transient():
    assert agent._is_transient(_http_error(429))
    assert agent._is_transient(APIConnectionError(request=_request()))
    assert agent._is_transient(APITimeoutError(request=_request()))


def test_request_errors_are_not_retried():
    assert not agent._is_transient(_http_error(400))
    assert not agent._is_transient(_http_error(401))
    assert not agent._is_transient(ValueError("invalid json"))


# --- retry behaviour ----------------------------------------------------------

def test_a_one_off_500_is_retried_and_ends_up_working():
    client = _FakeClient(_http_error(500), failures=1)
    assert agent._create_response(client, model="x") == "response"
    assert client.calls == 2


def test_it_gives_up_after_exhausting_the_attempts(monkeypatch):
    monkeypatch.setenv("API_RETRIES", "3")
    client = _FakeClient(_http_error(500), failures=99)
    with pytest.raises(APIStatusError):
        agent._create_response(client, model="x")
    assert client.calls == 3


def test_a_400_error_is_not_retried():
    client = _FakeClient(_http_error(400), failures=99)
    with pytest.raises(APIStatusError):
        agent._create_response(client, model="x")
    assert client.calls == 1


def test_retries_are_configurable(monkeypatch):
    monkeypatch.setenv("API_RETRIES", "1")   # 1 attempt = no retries
    client = _FakeClient(_http_error(500), failures=99)
    with pytest.raises(APIStatusError):
        agent._create_response(client, model="x")
    assert client.calls == 1


# --- effect on the panel ------------------------------------------------------

def test_a_failed_search_does_not_spend_daily_quota(monkeypatch):
    def boom(*a, **k):
        raise _http_error(500)

    monkeypatch.setattr(agent, "search_offers", boom)
    bid = db.create_search("caravana", "Madrid", "ES", 6)
    web.run_search(bid)

    assert db.runs_today() == 0
    error = db.get_search(bid)["ultimo_error"]
    assert "Error temporal de OpenAI (500)" in error
    assert bid not in web._running


def test_a_successful_search_does_spend_quota(fake_api, make_offer):
    fake_api({"summary": "r", "offers": [make_offer("https://x/a", "A", 100)]})
    bid = db.create_search("caravana", "Madrid", "ES", 6)
    web.run_search(bid)
    assert db.runs_today() == 1


def test_readable_messages_for_the_usual_errors():
    assert "429" in web._readable_error(_http_error(429))
    assert "OPENAI_API_KEY" in web._readable_error(_http_error(401))
    assert "No se pudo contactar" in web._readable_error(APIConnectionError(request=_request()))
