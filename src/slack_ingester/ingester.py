import asyncio
import os
from datetime import UTC, date, datetime, time
from typing import Any, Self

from slack_ingester.client import SlackClient
from slack_ingester.exceptions import SlackAuthError
from slack_ingester.models import IngestionResult, SlackFile, SlackMessage, SlackReaction


class SlackIngester:
    def __init__(self, token: str | None = None, *, timeout: float = 60.0) -> None:
        token = token or os.environ.get("SLACK_BOT_TOKEN")
        if not token:
            raise SlackAuthError("No Slack bot token provided. Pass token= or set SLACK_BOT_TOKEN.")
        self._client = SlackClient(token, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def ingest(
        self,
        channel_id: str,
        *,
        message_ts: str | None = None,
        thread_ts: str | None = None,
        oldest: datetime | date | None = None,
        latest: datetime | date | None = None,
        include_replies: bool = True,
        max_messages: int | None = None,
    ) -> IngestionResult:
        """Ingest messages from a Slack channel, a specific thread, or a single message.

        Args:
            channel_id: The Slack channel ID to ingest from.
            message_ts: Optional message timestamp. If provided, ingests only that single
                message. When ingesting a single message, the `oldest`, `latest`,
                `include_replies`, and `max_messages` parameters are ignored.
                Cannot be combined with `thread_ts`.
            thread_ts: Optional thread timestamp. If provided, ingests only that specific
                thread instead of the entire channel. When ingesting a thread, the
                `oldest`, `latest`, and `include_replies` parameters are ignored.
            oldest: Only fetch messages newer than this timestamp (inclusive).
                Ignored when `thread_ts` or `message_ts` is provided.
            latest: Only fetch messages older than this timestamp (inclusive).
                Ignored when `thread_ts` or `message_ts` is provided.
            include_replies: If True, fetch all thread replies for messages that have them.
                Ignored when `thread_ts` or `message_ts` is provided.
            max_messages: Maximum number of messages to fetch. If None, fetch all available.
                Ignored when `message_ts` is provided.

        Returns:
            IngestionResult containing the fetched messages and metadata.

        Raises:
            ValueError: If both `message_ts` and `thread_ts` are provided.
        """
        if message_ts is not None and thread_ts is not None:
            raise ValueError("Cannot specify both message_ts and thread_ts.")

        channel_info = await self._client.get_channel_info(channel_id)
        channel_name: str | None = channel_info.get("name") or None

        if message_ts is not None:
            parsed = await self._ingest_single_message(channel_id, message_ts)
        elif thread_ts is not None:
            parsed = await self._ingest_thread(channel_id, thread_ts, max_messages)
        else:
            parsed = await self._ingest_channel(
                channel_id,
                oldest=oldest,
                latest=latest,
                include_replies=include_replies,
                max_messages=max_messages,
            )

        messages = tuple(parsed)
        total_messages = len(messages) + sum(len(m.replies) for m in messages)

        return IngestionResult(
            channel_id=channel_id,
            channel_name=channel_name,
            messages=messages,
            total_messages=total_messages,
            oldest_ts=messages[-1].timestamp if messages else None,
            latest_ts=messages[0].timestamp if messages else None,
        )

    async def _ingest_single_message(self, channel_id: str, message_ts: str) -> list[SlackMessage]:
        batch, _ = await self._client.get_channel_history(
            channel_id,
            oldest=message_ts,
            latest=message_ts,
            limit=1,
        )
        return [_parse_message(m, channel_id) for m in batch[:1]]

    async def _ingest_thread(self, channel_id: str, thread_ts: str, max_messages: int | None) -> list[SlackMessage]:
        raw_messages = await self._client.get_thread_messages(channel_id, thread_ts)
        if max_messages is not None:
            raw_messages = raw_messages[:max_messages]
        return [_parse_message(m, channel_id) for m in raw_messages]

    async def _ingest_channel(
        self,
        channel_id: str,
        *,
        oldest: datetime | date | None,
        latest: datetime | date | None,
        include_replies: bool,
        max_messages: int | None,
    ) -> list[SlackMessage]:
        oldest_slack_ts = _to_slack_ts(oldest) if oldest is not None else None
        latest_slack_ts = (
            _to_slack_ts(latest, end_of_day=isinstance(latest, date) and not isinstance(latest, datetime))
            if latest is not None
            else None
        )

        raw_messages: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            remaining = (max_messages - len(raw_messages)) if max_messages is not None else 200
            limit = min(remaining, 200) if max_messages is not None else 200
            batch, cursor = await self._client.get_channel_history(
                channel_id,
                oldest=oldest_slack_ts,
                latest=latest_slack_ts,
                cursor=cursor,
                limit=limit,
            )
            raw_messages.extend(batch)
            if not cursor or (max_messages is not None and len(raw_messages) >= max_messages):
                break

        if max_messages is not None:
            raw_messages = raw_messages[:max_messages]

        parsed = [_parse_message(m, channel_id) for m in raw_messages]

        if include_replies:
            parsed = await self._fetch_and_attach_replies(channel_id, raw_messages, parsed)

        return parsed

    async def _fetch_and_attach_replies(
        self,
        channel_id: str,
        raw_messages: list[dict[str, Any]],
        parsed: list[SlackMessage],
    ) -> list[SlackMessage]:
        parents = [m for m in parsed if m.is_thread_parent]
        if not parents:
            return parsed

        replies_map: dict[str, tuple[SlackMessage, ...]] = {}

        async def _fetch(msg: SlackMessage) -> None:
            raw_thread = await self._client.get_thread_messages(channel_id, msg.id)
            replies_map[msg.id] = tuple(_parse_message(r, channel_id) for r in raw_thread[1:])

        async with asyncio.TaskGroup() as tg:
            for parent in parents:
                tg.create_task(_fetch(parent))

        return [
            _parse_message(raw_messages[i], channel_id, replies_map.get(msg.id, ())) for i, msg in enumerate(parsed)
        ]


def _ts_to_datetime(ts: str) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=UTC)


def _to_slack_ts(value: datetime | date, *, end_of_day: bool = False) -> str:
    """Convert a datetime or date to a Slack epoch timestamp string.

    For ``date`` objects, the timestamp is midnight UTC of that date by default.
    When *end_of_day* is ``True`` (useful for *latest*), it uses 23:59:59.999999 UTC instead.

    For ``datetime`` objects, naïve datetimes are assumed to be UTC.
    """
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    else:
        t = time.max if end_of_day else time.min
        dt = datetime.combine(value, t, tzinfo=UTC)
    return f"{dt.timestamp():.6f}"


def _parse_reaction(raw: dict[str, Any]) -> SlackReaction:
    return SlackReaction(
        name=str(raw.get("name", "")),
        count=int(raw.get("count", 0)),
        users=tuple(str(u) for u in raw.get("users", [])),
    )


def _parse_file(raw: dict[str, Any]) -> SlackFile:
    return SlackFile(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        mimetype=str(raw.get("mimetype", "")),
        size=int(raw.get("size", 0)),
        url_private=raw.get("url_private") or None,
        permalink=raw.get("permalink") or None,
    )


def _parse_message(
    raw: dict[str, Any],
    channel_id: str,
    replies: tuple[SlackMessage, ...] = (),
) -> SlackMessage:
    ts = str(raw.get("ts", "0"))
    thread_ts: str | None = raw.get("thread_ts") or None
    reply_count = int(raw.get("reply_count", 0))
    is_thread_parent = reply_count > 0 and thread_ts == ts
    subtype: str | None = raw.get("subtype") or None
    user_id: str | None = raw.get("user") or None
    is_bot = bool(raw.get("bot_id")) or subtype == "bot_message" or user_id == "USLACKBOT"

    return SlackMessage(
        id=ts,
        channel_id=channel_id,
        user_id=user_id,
        text=str(raw.get("text", "")),
        timestamp=_ts_to_datetime(ts),
        thread_ts=thread_ts,
        is_thread_parent=is_thread_parent,
        reply_count=reply_count,
        replies=replies,
        files=tuple(_parse_file(f) for f in raw.get("files", [])),
        reactions=tuple(_parse_reaction(r) for r in raw.get("reactions", [])),
        is_bot=is_bot,
        subtype=subtype,
    )
