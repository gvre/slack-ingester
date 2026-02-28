from dataclasses import dataclass
from datetime import datetime
from typing import Self


@dataclass(slots=True, frozen=True)
class SlackReaction:
    name: str
    count: int
    users: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class SlackFile:
    id: str
    name: str
    mimetype: str
    size: int
    url_private: str | None
    permalink: str | None


@dataclass(slots=True, frozen=True)
class SlackMessage:
    id: str
    channel_id: str
    user_id: str | None
    text: str
    timestamp: datetime
    thread_ts: str | None
    is_thread_parent: bool
    reply_count: int
    replies: tuple[Self, ...]
    files: tuple[SlackFile, ...]
    reactions: tuple[SlackReaction, ...]
    is_bot: bool
    subtype: str | None


@dataclass(slots=True, frozen=True)
class IngestionResult:
    channel_id: str
    channel_name: str | None
    messages: tuple[SlackMessage, ...]
    total_messages: int
    oldest_ts: datetime | None
    latest_ts: datetime | None
