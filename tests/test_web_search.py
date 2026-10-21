"""Exa uses bounded official requests and exposes only sanitized failures."""

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from org_harness.config import Settings
from org_harness.tools import ExpectedToolInputError
from org_harness.web_search import ExaContentUnavailable, ExaSearchError, ExaWebClient

KEY = "private-exa-key-do-not-disclose"
URL = "https://example.com/ภาษาไทย"


def settings(**changes):
    return Settings(
        _env_file=None,
        exa_api_key=changes.pop("exa_api_key", KEY),
        openai_api_key="native-private-key",
        openai_base_url="https://api.openai.com/v1",
        zai_api_key=changes.pop("zai_api_key", ""),
        **changes,
    )


@pytest.mark.parametrize(
    ("selected", "key", "expected", "configured"),
    [
        ("auto", KEY, "exa", True),
        ("auto", "", "zai_mcp", False),
        ("auto", "   ", "zai_mcp", False),
        ("exa", "", "exa", False),
        ("zai_mcp", KEY, "zai_mcp", False),
    ],
)
def test_provider_selection_and_public_settings_do_not_expose_credentials(
    selected, key, expected, configured
):
    value = settings(exa_api_key=key, web_search_provider=selected)
    assert value.selected_web_search_provider() == expected
    public = value.public_settings()
    assert public["web_search"] == {"provider": expected, "configured": configured}
    assert KEY not in json.dumps(public) and "native-private-key" not in json.dumps(public)
    assert KEY not in repr(value) and KEY not in value.model_dump_json()
    assert public["worker_timeout"] == 3600


def test_explicit_legacy_uses_zai_credentials_and_exa_env_key_is_loaded(tmp_path, monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    path = tmp_path / ".env"
    path.write_text(f"EXA_API_KEY={KEY}\n")
    value = Settings(_env_file=path)
    assert value.selected_web_search_provider() == "exa"
    assert value.exa_api_key.get_secret_value() == KEY
    legacy = settings(web_search_provider="zai_mcp", zai_api_key="private-zai-key")
    assert legacy.public_settings()["web_search"] == {"provider": "zai_mcp", "configured": True}
    assert "private-zai-key" not in json.dumps(legacy.public_settings())


@pytest.mark.parametrize("timeout", [0, 121, float("nan"), float("inf")])
def test_exa_timeout_is_finite_and_bounded(timeout):
    with pytest.raises(ValidationError):
        settings(exa_timeout=timeout)


async def test_official_search_and_content_payloads_preserve_sources_and_provenance():
    requests = []
    source = {"url": URL, "title": "Example", "text": "บทความ 😀\n\tContent."}

    def response(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "requestId": "request-one",
                "results": [source],
                **(
                    {"statuses": [{"id": URL, "status": "success"}]}
                    if request.url.path == "/contents"
                    else {}
                ),
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
        client = ExaWebClient(settings(), client=http)
        search = await client.search("Three.js ภาษาไทย")
        read = await client.read(URL)
        await client.close()
        assert not http.is_closed
    assert [str(request.url) for request in requests] == [
        "https://api.exa.ai/search",
        "https://api.exa.ai/contents",
    ]
    assert all(request.headers["x-api-key"] == KEY for request in requests)
    assert all(request.headers["content-type"] == "application/json" for request in requests)
    assert json.loads(requests[0].content) == {
        "query": "Three.js ภาษาไทย",
        "type": "auto",
        "numResults": 5,
        "contents": {"text": {"maxCharacters": 12000}},
    }
    assert json.loads(requests[1].content) == {"urls": [URL], "text": {"maxCharacters": 20000}}
    assert search["query"] == "Three.js ภาษาไทย" and read["requested_url"] == URL
    assert search["provider"] == read["provider"] == "exa"
    assert search["results"] == read["results"] == [source]
    assert search["requestId"] == read["requestId"] == "request-one"
    assert search["text_max_characters"] == 12000 and read["text_max_characters"] == 20000
    assert not search["source_text_may_be_truncated"] and not read["source_text_may_be_truncated"]


@pytest.mark.parametrize(("method", "limit"), [("search", 12000), ("read", 20000)])
async def test_requested_source_text_bound_is_explicit_in_result(method, limit):
    raw = "A" * limit
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"results": [{"url": URL, "text": raw}]})
        )
    ) as http:
        value = await getattr(ExaWebClient(settings(), client=http), method)(URL)
    assert value["results"][0]["text"] == raw
    assert value["source_text_may_be_truncated"] and value["text_max_characters"] == limit


async def test_empty_search_is_valid_but_empty_content_is_a_typed_failure():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"results": []}))
    ) as http:
        client = ExaWebClient(settings(), client=http)
        assert (await client.search("No matches"))["results"] == []
        with pytest.raises(ExaContentUnavailable, match="no readable"):
            await client.read(URL)


@pytest.mark.parametrize("status", [301, 400, 401, 402, 403, 429, 500, 503])
@pytest.mark.parametrize("method", ["search", "read"])
async def test_http_failures_never_echo_bodies_or_follow_auth_redirects(status, method):
    calls = []

    def response(request):
        calls.append(request)
        return httpx.Response(
            status,
            text=f"PRIVATE response {KEY}",
            headers={"location": "https://untrusted.example"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(response), follow_redirects=True
    ) as http:
        with pytest.raises(ExaSearchError) as caught:
            await getattr(ExaWebClient(settings(), client=http), method)(URL)
    assert str(status) in str(caught.value)
    assert KEY not in str(caught.value) and "PRIVATE" not in str(caught.value)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"results": None},
        {"results": [None]},
        {"results": [{}]},
        {"results": [{"url": "file:///secret"}]},
        {"results": [{"url": URL, "text": 123}]},
        {"results": [{"url": URL, "text": "bad\ud800"}]},
        {"results": [], "costDollars": float("nan")},
    ],
)
async def test_malformed_result_structures_raise_sanitized_errors(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=json.dumps(payload, ensure_ascii=True))
        )
    ) as http:
        with pytest.raises(ExaSearchError) as caught:
            await ExaWebClient(settings(), client=http).search("private query")
    assert "private query" not in str(caught.value) and KEY not in str(caught.value)


@pytest.mark.parametrize("body", [b"PRIVATE non-JSON", b"\xff", b'{"results":['])
async def test_non_json_success_bodies_are_typed_failures(body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    ) as http:
        with pytest.raises(ExaSearchError, match="malformed JSON") as caught:
            await ExaWebClient(settings(), client=http).search("query")
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize(
    "statuses",
    [
        None,
        {},
        [],
        [{}],
        [{"status": "error", "error": {"tag": KEY}}],
        [{"id": URL, "status": "pending"}],
        [{"id": URL, "status": []}],
        [{"id": URL, "status": "error", "error": "malformed"}],
        [{"id": URL, "status": "error", "error": {"tag": 123}}],
        [{"id": URL, "status": "error", "error": {"httpStatusCode": "404"}}],
        [{"id": URL, "status": "error", "error": {"httpStatusCode": True}}],
        [{"id": URL, "status": "error", "error": {"httpStatusCode": 999}}],
        [{"id": URL, "status": "success", "error": {}}],
        [{"id": URL, "status": "success", "error": {"tag": "CRAWL_NOT_FOUND"}}],
        [
            {"id": URL, "status": "error", "error": {"tag": "CRAWL_NOT_FOUND"}},
            {"id": URL, "status": "not-a-status"},
        ],
    ],
)
async def test_malformed_or_contradictory_statuses_remain_provider_failures(statuses):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"results": [{"url": URL, "text": "body"}], "statuses": statuses}
            )
        )
    ) as http:
        with pytest.raises(ExaSearchError, match="content statuses") as caught:
            await ExaWebClient(settings(), client=http).read(URL)
    assert KEY not in str(caught.value)


@pytest.mark.parametrize("text", [None, "", "   "])
async def test_reader_requires_actual_nonempty_text(text):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"results": [{"url": URL, "text": text}]})
        )
    ) as http:
        with pytest.raises(ExaContentUnavailable, match="no readable"):
            await ExaWebClient(settings(), client=http).read(URL)


@pytest.mark.parametrize(
    "tag",
    [
        "CRAWL_NOT_FOUND",
        "CRAWL_HTTP_403",
        "CRAWL_TIMEOUT",
        "CRAWL_LIVECRAWL_TIMEOUT",
        "SOURCE_NOT_AVAILABLE",
        "UNSUPPORTED_URL",
        "CRAWL_UNKNOWN_ERROR",
        KEY,
    ],
)
async def test_url_level_failures_are_actionable_tool_input_errors_without_fallback(tag):
    calls = []
    failed_url = "https://github.com/advisories/GHSA-r2gr-w3c8-wvqv"

    def response(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "results": [],
                "statuses": [
                    {
                        "id": failed_url,
                        "status": "error",
                        "error": {"tag": tag, "httpStatusCode": 404},
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
        with pytest.raises(ExaContentUnavailable) as caught:
            await ExaWebClient(settings(), client=http).read(failed_url)
    assert isinstance(caught.value, ExpectedToolInputError)
    assert not isinstance(caught.value, ExaSearchError)
    assert "canonical public URL" in str(caught.value)
    assert "previously stored source artifact" in str(caught.value)
    assert "not source evidence" in str(caught.value)
    assert KEY not in str(caught.value)
    if tag != KEY:
        assert tag in str(caught.value)
    assert len(calls) == 1 and calls[0].url.host == "api.exa.ai"
    assert json.loads(calls[0].content)["urls"] == [failed_url]


async def test_successful_content_status_with_nullable_error_is_valid():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "results": [{"url": URL, "text": "Source evidence"}],
                    "statuses": [{"id": URL, "status": "success", "error": None}],
                },
            )
        )
    ) as http:
        result = await ExaWebClient(settings(), client=http).read(URL)
    assert result["results"][0]["text"] == "Source evidence"


@pytest.mark.parametrize("kind", [httpx.ConnectError, httpx.ReadTimeout])
@pytest.mark.parametrize("method", ["search", "read"])
async def test_network_errors_are_sanitized(kind, method):
    def fail(request):
        raise kind(f"PRIVATE network exception {KEY}", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as http:
        with pytest.raises(ExaSearchError) as caught:
            await getattr(ExaWebClient(settings(), client=http), method)(URL)
    assert KEY not in str(caught.value) and "PRIVATE" not in str(caught.value)


async def test_streaming_response_has_total_deadline_and_size_bound():
    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(0.1)
            yield b'{"results":[]}'

    for body in (b"x" * 2_000_001, SlowBody()):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _, body=body: (
                    httpx.Response(200, stream=body)
                    if isinstance(body, SlowBody)
                    else httpx.Response(200, content=body)
                )
            )
        ) as http:
            with pytest.raises(ExaSearchError, match="limit|timed out"):
                await ExaWebClient(settings(exa_timeout=0.01), client=http).search("query")


async def test_missing_key_and_invalid_inputs_never_make_http_requests():
    calls = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: calls.append(request))
    ) as http:
        client = ExaWebClient(settings(exa_api_key=""), client=http)
        with pytest.raises(ExaSearchError, match="not configured"):
            await client.search("valid query")
        for url in (
            "not-a-url",
            "file:///secret",
            "https://example.com:invalid",
            "https://example.com/a b",
            "https://example.com/\x00",
        ):
            with pytest.raises(ExpectedToolInputError):
                await client.read(url)
        for query in ("", " ", "bad\x00", "x" * 50001):
            with pytest.raises(ExpectedToolInputError):
                await client.search(query)
    assert calls == []


async def test_owned_client_is_created_lazily_and_closed(monkeypatch):
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"results": []}))
    )
    created = []

    def factory(**kwargs):
        created.append(kwargs)
        return http

    monkeypatch.setattr("org_harness.web_search.httpx.AsyncClient", factory)
    client = ExaWebClient(settings())
    assert created == []
    await client.search("query")
    assert created and created[0]["timeout"] == 30
    await client.close()
    assert http.is_closed
