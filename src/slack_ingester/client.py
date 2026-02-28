from typing import Any, Self

import httpx

from slack_ingester.exceptions import (
    SlackAuthError,
    SlackChannelNotFoundError,
    SlackIngesterError,
    SlackRateLimitError,
)

_BASE_URL = "https://slack.com/api"
_AUTH_ERRORS = {"invalid_auth", "not_authed", "token_revoked", "account_inactive"}
_CHANNEL_ERRORS = {"channel_not_found", "not_in_channel", "missing_scope"}


def _raise_for_slack_response(response: httpx.Response) -> dict[str, Any]:
    if response.status_code == 429:
        retry_after = int(response.headers.get("Retry-After", 1))
        raise SlackRateLimitError("Rate limited by Slack API", retry_after=retry_after)
    try:
        data: dict[str, Any] = response.json()
    except Exception as exc:
        raise SlackIngesterError(
            f"Non-JSON response from Slack API (HTTP {response.status_code})"
        ) from exc
    if data.get("ok"):
        return data
    code = str(data.get("error", "unknown_error"))
    if code in _AUTH_ERRORS:
        raise SlackAuthError(f"Slack authentication failed: {code}")
    if code in _CHANNEL_ERRORS:
        raise SlackChannelNotFoundError(f"Channel not found or inaccessible: {code}")
    raise SlackIngesterError(f"Slack API error: {code}")


class SlackClient:
    def __init__(self, token: str, *, timeout: float = 60.0) -> None:
        self._http = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def get_channel_info(self, channel_id: str) -> dict[str, Any]:
        response = await self._http.get("/conversations.info", params={"channel": channel_id})
        data = _raise_for_slack_response(response)
        return dict(data["channel"])

    async def get_channel_history(
        self,
        channel_id: str,
        *,
        oldest: str | None = None,
        latest: str | None = None,
        cursor: str | None = None,
        limit: int = 200,
    ) -> tuple[list[dict[str, Any]], str | None]:
        params: dict[str, Any] = {"channel": channel_id, "limit": limit, "inclusive": True}
        if oldest is not None:
            params["oldest"] = oldest
        if latest is not None:
            params["latest"] = latest
        if cursor is not None:
            params["cursor"] = cursor
        response = await self._http.get("/conversations.history", params=params)
        data = _raise_for_slack_response(response)
        messages: list[dict[str, Any]] = data["messages"]
        next_cursor: str | None = data.get("response_metadata", {}).get("next_cursor") or None
        return messages, next_cursor

    async def get_thread_messages(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> list[dict[str, Any]]:
        """Return all messages in a thread, including the parent as the first element."""
        messages: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {
                "channel": channel_id,
                "ts": thread_ts,
                "limit": 200,
            }
            if cursor is not None:
                params["cursor"] = cursor
            response = await self._http.get("/conversations.replies", params=params)
            data = _raise_for_slack_response(response)
            batch: list[dict[str, Any]] = data["messages"]
            # Slack includes the parent in every page; keep it only from the first.
            messages.extend(batch if not messages else batch[1:])
            next_cursor: str | None = data.get("response_metadata", {}).get("next_cursor") or None
            if not next_cursor:
                break
            cursor = next_cursor
        return messages
