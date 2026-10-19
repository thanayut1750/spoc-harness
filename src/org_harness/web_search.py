"""Bounded Exa web search and content retrieval using its official HTTP API."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from org_harness.config import Settings
from org_harness.text_safety import contains_invalid_json_value
from org_harness.tools import ExpectedToolInputError

_EXA_BASE_URL = "https://api.exa.ai"
_MAX_RESPONSE_BYTES = 2_000_000


class ExaSearchError(Exception):
    """An Exa configuration, service, or response failure safe to display publicly."""


class ExaContentUnavailable(ExpectedToolInputError):
    """A single source could not be read; the agent can select another source."""


_CONTENT_ERROR_TAGS = {
    "CRAWL_NOT_FOUND",
    "CRAWL_TIMEOUT",
    "CRAWL_LIVECRAWL_TIMEOUT",
    "SOURCE_NOT_AVAILABLE",
    "UNSUPPORTED_URL",
    "CRAWL_UNKNOWN_ERROR",
}


def _content_error_tag(statuses: Any) -> str | None:
    if not isinstance(statuses, list) or not statuses:
        raise ExaSearchError("Exa returned invalid content statuses")
    failures = []
    for item in statuses:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not item["id"].strip()
            or not isinstance(item.get("status"), str)
            or item.get("status") not in {"success", "error"}
            or item.get("source") is not None
            and not isinstance(item["source"], str)
        ):
            raise ExaSearchError("Exa returned invalid content statuses")
        error = item.get("error")
        if error is not None and (
            not isinstance(error, dict)
            or "tag" in error
            and not isinstance(error["tag"], str)
            or error.get("httpStatusCode") is not None
            and (
                type(error["httpStatusCode"]) is not int
                or not 100 <= error["httpStatusCode"] <= 599
            )
        ):
            raise ExaSearchError("Exa returned invalid content statuses")
        if item["status"] == "success" and error is not None:
            raise ExaSearchError("Exa returned contradictory content statuses")
        if item["status"] == "error":
            tag = error.get("tag", "") if error else ""
            # Exa's tag set is open-ended. Display only documented tag names;
            # unknown tags still describe a page-level failure, without echoing
            # untrusted provider details or source material.
            failures.append(
                tag
                if tag in _CONTENT_ERROR_TAGS or re.fullmatch(r"CRAWL_HTTP_[1-5][0-9]{2}", tag)
                else "CONTENT_UNAVAILABLE"
            )
    return failures[0] if failures else None


def _valid_url(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 2048
        or contains_invalid_json_value(value)
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and parsed.port != 0
    except ValueError:
        return False


class ExaWebClient:
    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client
        self._owns_client = client is None

    async def close(self) -> None:
        """Close our connection pool; injected clients remain owned by their caller."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def _post(self, endpoint: str, payload: dict) -> dict:
        key = self.settings.exa_api_key.get_secret_value()
        if not key.strip():
            raise ExaSearchError("Exa is selected but EXA_API_KEY is not configured")
        if not key.isascii() or any(
            ord(character) < 33 or ord(character) > 126 for character in key
        ):
            raise ExaSearchError("Exa API credentials have an invalid format")
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.settings.exa_timeout, follow_redirects=False
            )
        try:
            async with asyncio.timeout(self.settings.exa_timeout):
                async with self._client.stream(
                    "POST",
                    _EXA_BASE_URL + endpoint,
                    json=payload,
                    headers={"x-api-key": key, "Accept": "application/json"},
                    timeout=self.settings.exa_timeout,
                    follow_redirects=False,
                ) as response:
                    if not 200 <= response.status_code < 300:
                        raise ExaSearchError(f"Exa request failed (HTTP {response.status_code})")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                            raise ExaSearchError("Exa response exceeds the bounded source limit")
                        body.extend(chunk)
        except (TimeoutError, httpx.TimeoutException):
            raise ExaSearchError("Exa request timed out") from None
        except httpx.HTTPError as exc:
            raise ExaSearchError(f"Exa connection failed ({type(exc).__name__})") from None
        try:
            result = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError):
            raise ExaSearchError("Exa returned malformed JSON") from None
        if (
            not isinstance(result, dict)
            or contains_invalid_json_value(result)
            or not isinstance(result.get("results"), list)
        ):
            raise ExaSearchError("Exa returned an invalid result structure")
        for item in result["results"]:
            if not isinstance(item, dict) or not _valid_url(item.get("url")):
                raise ExaSearchError("Exa returned an invalid search result")
            if any(
                item.get(field) is not None and not isinstance(item[field], str)
                for field in ("title", "text", "id", "author", "publishedDate")
            ):
                raise ExaSearchError("Exa returned invalid result content")
        return {**result, "provider": "exa"}

    async def search(self, query: str) -> dict:
        if (
            not isinstance(query, str)
            or not query.strip()
            or len(query) > 50000
            or contains_invalid_json_value(query)
        ):
            raise ExpectedToolInputError(
                "Search query must contain valid nonempty text within 50000 characters"
            )
        result = await self._post(
            "/search",
            {
                "query": query,
                "type": "auto",
                "numResults": 5,
                "contents": {"text": {"maxCharacters": 12000}},
            },
        )
        return {
            **result,
            "query": query,
            "text_max_characters": 12000,
            "source_text_may_be_truncated": any(
                len(item.get("text") or "") >= 12000 for item in result["results"]
            ),
        }

    async def read(self, url: str) -> dict:
        if not _valid_url(url):
            raise ExpectedToolInputError(
                "Reference URL must be a valid HTTP or HTTPS URL within 2048 characters"
            )
        result = await self._post("/contents", {"urls": [url], "text": {"maxCharacters": 20000}})
        if "statuses" in result and (tag := _content_error_tag(result["statuses"])):
            raise ExaContentUnavailable(
                f"Exa could not retrieve the requested page content ({tag}). "
                "Verify the URL, choose another canonical public URL, or use a previously stored "
                "source artifact. This failed fetch is not source evidence."
            )
        if not result["results"] or any(
            not isinstance(item.get("text"), str) or not item["text"].strip()
            for item in result["results"]
        ):
            raise ExaContentUnavailable(
                "Exa returned no readable page content. Choose another canonical public URL or "
                "use a previously stored source artifact; empty content is not source evidence."
            )
        return {
            **result,
            "requested_url": url,
            "text_max_characters": 20000,
            "source_text_may_be_truncated": any(
                len(item["text"]) >= 20000 for item in result["results"]
            ),
        }
