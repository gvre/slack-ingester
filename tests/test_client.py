from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from slack_ingester.client import SlackClient
from slack_ingester.exceptions import (
    SlackAuthError,
    SlackChannelNotFoundError,
    SlackIngesterError,
    SlackRateLimitError,
)


def make_response(
    payload: dict[str, Any],
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=payload,
        headers=headers or {},
    )


def make_html_response(status_code: int = 502) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=b"<html><body>Bad Gateway</body></html>",
        headers={"Content-Type": "text/html"},
    )


def make_rate_limit_response(retry_after: int = 30) -> httpx.Response:
    return httpx.Response(
        status_code=429,
        json={},
        headers={"Retry-After": str(retry_after)},
    )


@pytest.fixture
async def client() -> AsyncGenerator[SlackClient]:
    async with SlackClient(token="xoxb-fake-token") as c:
        yield c


class TestGetChannelInfo:
    async def test_maps_invalid_auth(self, client):
        with patch.object(
            client._http,
            "get",
            new=AsyncMock(return_value=make_response({"ok": False, "error": "invalid_auth"})),
        ):
            with pytest.raises(SlackAuthError):
                await client.get_channel_info("C001")

    async def test_maps_channel_not_found(self, client):
        with patch.object(
            client._http,
            "get",
            new=AsyncMock(return_value=make_response({"ok": False, "error": "channel_not_found"})),
        ):
            with pytest.raises(SlackChannelNotFoundError):
                await client.get_channel_info("C001")

    async def test_maps_not_in_channel(self, client):
        with patch.object(
            client._http,
            "get",
            new=AsyncMock(return_value=make_response({"ok": False, "error": "not_in_channel"})),
        ):
            with pytest.raises(SlackChannelNotFoundError):
                await client.get_channel_info("C001")

    async def test_maps_ratelimited(self, client):
        with patch.object(
            client._http,
            "get",
            new=AsyncMock(return_value=make_rate_limit_response(retry_after=30)),
        ):
            with pytest.raises(SlackRateLimitError) as exc_info:
                await client.get_channel_info("C001")
            assert exc_info.value.retry_after == 30

    async def test_maps_unknown_error(self, client):
        with patch.object(
            client._http,
            "get",
            new=AsyncMock(return_value=make_response({"ok": False, "error": "some_weird_error"})),
        ):
            with pytest.raises(SlackIngesterError):
                await client.get_channel_info("C001")

    async def test_non_json_response_raises_ingester_error(self, client):
        with patch.object(
            client._http,
            "get",
            new=AsyncMock(return_value=make_html_response(502)),
        ):
            with pytest.raises(SlackIngesterError, match="Non-JSON response"):
                await client.get_channel_info("C001")

    async def test_success(self, client):
        channel = {"ok": True, "channel": {"id": "C001", "name": "general"}}
        with patch.object(
            client._http,
            "get",
            new=AsyncMock(return_value=make_response(channel)),
        ):
            info = await client.get_channel_info("C001")
        assert info["name"] == "general"


class TestGetChannelHistory:
    async def test_returns_messages_and_cursor(self, client):
        payload = {
            "ok": True,
            "messages": [{"ts": "1700000000.0", "text": "hi"}],
            "response_metadata": {"next_cursor": "abc123"},
        }
        with patch.object(client._http, "get", new=AsyncMock(return_value=make_response(payload))):
            messages, cursor = await client.get_channel_history("C001")
        assert len(messages) == 1
        assert cursor == "abc123"

    async def test_no_next_cursor_returns_none(self, client):
        payload = {
            "ok": True,
            "messages": [],
            "response_metadata": {"next_cursor": ""},
        }
        with patch.object(client._http, "get", new=AsyncMock(return_value=make_response(payload))):
            _, cursor = await client.get_channel_history("C001")
        assert cursor is None


class TestGetChannelHistoryWithParams:
    async def test_with_oldest_param(self, client):
        mock_get = AsyncMock(
            return_value=make_response(
                {
                    "ok": True,
                    "messages": [],
                    "response_metadata": {"next_cursor": ""},
                }
            )
        )
        with patch.object(client._http, "get", new=mock_get):
            await client.get_channel_history("C001", oldest="1700000000.0")

        call_params = mock_get.call_args.kwargs["params"]
        assert call_params["oldest"] == "1700000000.0"

    async def test_with_latest_param(self, client):
        mock_get = AsyncMock(
            return_value=make_response(
                {
                    "ok": True,
                    "messages": [],
                    "response_metadata": {"next_cursor": ""},
                }
            )
        )
        with patch.object(client._http, "get", new=mock_get):
            await client.get_channel_history("C001", latest="1700000001.0")

        call_params = mock_get.call_args.kwargs["params"]
        assert call_params["latest"] == "1700000001.0"

    async def test_with_cursor_param(self, client):
        mock_get = AsyncMock(
            return_value=make_response(
                {
                    "ok": True,
                    "messages": [],
                    "response_metadata": {"next_cursor": ""},
                }
            )
        )
        with patch.object(client._http, "get", new=mock_get):
            await client.get_channel_history("C001", cursor="cursor123")

        call_params = mock_get.call_args.kwargs["params"]
        assert call_params["cursor"] == "cursor123"


class TestGetThreadMessages:
    async def test_returns_parent_and_replies(self, client):
        payload = {
            "ok": True,
            "messages": [
                {"ts": "1700000000.0", "text": "parent"},
                {"ts": "1700000001.0", "text": "reply1"},
            ],
            "response_metadata": {"next_cursor": ""},
        }
        with patch.object(client._http, "get", new=AsyncMock(return_value=make_response(payload))):
            messages = await client.get_thread_messages("C001", "1700000000.0")
        assert len(messages) == 2
        assert messages[0]["text"] == "parent"
        assert messages[1]["text"] == "reply1"

    async def test_pagination_deduplicates_parent(self, client):
        call_count = 0

        async def side_effect(*args: object, **kwargs: object) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return make_response(
                    {
                        "ok": True,
                        "messages": [
                            {"ts": "1700000000.0", "text": "parent"},
                            {"ts": "1700000001.0", "text": "reply1"},
                        ],
                        "response_metadata": {"next_cursor": "cursor123"},
                    }
                )
            else:
                return make_response(
                    {
                        "ok": True,
                        "messages": [
                            {"ts": "1700000000.0", "text": "parent"},
                            {"ts": "1700000002.0", "text": "reply2"},
                        ],
                        "response_metadata": {"next_cursor": ""},
                    }
                )

        with patch.object(client._http, "get", new=AsyncMock(side_effect=side_effect)):
            messages = await client.get_thread_messages("C001", "1700000000.0")

        # Parent appears once, followed by replies from both pages.
        assert call_count == 2
        assert len(messages) == 3
        assert messages[0]["text"] == "parent"
        assert messages[1]["text"] == "reply1"
        assert messages[2]["text"] == "reply2"
