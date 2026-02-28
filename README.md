# slack-ingester

An async Python library for ingesting and parsing Slack channel messages and threads.

Built on top of [httpx](https://www.python-httpx.org/) for async HTTP, `slack-ingester` provides a clean, high-level interface to fetch channel history, thread replies, and associated metadata (reactions, files) from the Slack API, all with automatic pagination, concurrent reply fetching, and immutable data models.

## Features

- **Fully async**: powered by `httpx.AsyncClient` and `asyncio.TaskGroup`
- **Channel history ingestion**: fetch all messages from a channel with automatic cursor-based pagination
- **Thread ingestion**: fetch all replies from a specific thread
- **Date filtering**: restrict results by `oldest` / `latest` using `datetime` or `date` objects
- **Concurrent reply fetching**: thread replies for multiple parent messages are fetched concurrently
- **Message limits**: cap the number of messages returned with `max_messages`
- **Immutable data models**: frozen dataclasses with `__slots__` for memory efficiency and safety
- **Rich message data**: reactions, file attachments, bot detection, and thread metadata
- **Structured error handling**: typed exceptions for auth failures, missing channels, and rate limits

## Requirements

- Python 3.13+
- A Slack Bot Token (`xoxb-...`) with the necessary scopes

### Slack Bot Token Scopes

Your Slack app must have the following OAuth scopes:

| Scope | Purpose |
|---|---|
| `channels:history` | Read messages from public channels |
| `channels:read` | View basic channel info |
| `groups:history` | Read messages from private channels |
| `groups:read` | View basic info about private channels |

## Installation

### Using uv (recommended)

```
uv add slack-ingester
```

### Using pip

```
pip install slack-ingester
```

### From source

```
git clone https://github.com/gvre/slack-ingester.git
cd slack-ingester
uv sync
```

## Quick Start

```python
import asyncio
from slack_ingester import SlackIngester

async def main():
    # Token is read from SLACK_BOT_TOKEN env var, or pass it explicitly
    ingester = SlackIngester(token="xoxb-your-token")

    # Fetch all messages from a channel (including thread replies)
    result = await ingester.ingest("C1234567890")

    print(f"Channel: {result.channel_name}")
    print(f"Total messages: {result.total_messages}")

    for msg in result.messages:
        print(f"[{msg.timestamp}] {msg.user_id}: {msg.text}")

        for reply in msg.replies:
            print(f"  ↳ [{reply.timestamp}] {reply.user_id}: {reply.text}")

asyncio.run(main())
```

## Usage

### Configuration

The `SlackIngester` accepts a Slack Bot Token in two ways:

1. **Explicitly** via the `token` parameter:
   ```python
   ingester = SlackIngester(token="xoxb-your-token")
   ```

2. **Via environment variable** `SLACK_BOT_TOKEN`:
   ```
   export SLACK_BOT_TOKEN=xoxb-your-token
   ```
   ```python
   ingester = SlackIngester()  # reads from SLACK_BOT_TOKEN
   ```

If neither is provided, a `SlackAuthError` is raised immediately.

### Ingesting Channel History

```python
from datetime import date, datetime, UTC
from slack_ingester import SlackIngester

ingester = SlackIngester()

# Fetch all messages from a channel
result = await ingester.ingest("C1234567890")

# Fetch without thread replies (faster, skips conversations.replies calls)
result = await ingester.ingest("C1234567890", include_replies=False)

# Limit the number of messages
result = await ingester.ingest("C1234567890", max_messages=100)

# Filter by date range using datetime objects
result = await ingester.ingest(
    "C1234567890",
    oldest=datetime(2024, 6, 1, tzinfo=UTC),
    latest=datetime(2024, 6, 30, 23, 59, 59, tzinfo=UTC),
)

# Filter by date range using date objects
# - `oldest` as a date uses midnight UTC (start of day)
# - `latest` as a date uses 23:59:59.999999 UTC (end of day)
result = await ingester.ingest(
    "C1234567890",
    oldest=date(2024, 6, 1),
    latest=date(2024, 6, 30),
)
```

### Ingesting a Specific Thread

When a `thread_ts` is provided, the ingester fetches only the messages within that thread. The `oldest`, `latest`, and `include_replies` parameters are **ignored** in thread mode.

```python
# Fetch all messages from a specific thread
result = await ingester.ingest(
    "C1234567890",
    thread_ts="1700000000.000100",
)

print(f"Thread has {result.total_messages} messages")
for msg in result.messages:
    print(f"  {msg.user_id}: {msg.text}")
```

### Ingesting a Single Message

When a `message_ts` is provided, the ingester fetches only that specific message. All other parameters except `channel_id` are ignored, and `message_ts` cannot be combined with `thread_ts`.

```python
# Fetch a single message by its timestamp
result = await ingester.ingest(
    "C1234567890",
    message_ts="1700000000.000100",
)

if result.messages:
    msg = result.messages[0]
    print(f"{msg.user_id}: {msg.text}")
```

### Discovering Threads

You can find threads by first ingesting a channel without replies, then drilling into individual threads:

```python
# First pass: get top-level messages only
result = await ingester.ingest("C1234567890", include_replies=False)

for msg in result.messages:
    if msg.is_thread_parent:
        print(f"Thread: {msg.thread_ts} ({msg.reply_count} replies)")

        # Fetch the full thread
        thread = await ingester.ingest("C1234567890", thread_ts=msg.thread_ts)
        for reply in thread.messages:
            print(f"  {reply.user_id}: {reply.text}")
```

### Working with Message Data

```python
result = await ingester.ingest("C1234567890")

for msg in result.messages:
    # Basic message info
    print(f"ID: {msg.id}")
    print(f"User: {msg.user_id}")
    print(f"Text: {msg.text}")
    print(f"Time: {msg.timestamp}")  # datetime object (UTC)
    print(f"Bot: {msg.is_bot}")

    # Reactions
    for reaction in msg.reactions:
        print(f"  :{reaction.name}: x{reaction.count} by {reaction.users}")

    # File attachments
    for file in msg.files:
        print(f"  📎 {file.name} ({file.mimetype}, {file.size} bytes)")
        print(f"     URL: {file.url_private}")
        print(f"     Permalink: {file.permalink}")

    # Thread info
    if msg.is_thread_parent:
        print(f"  Thread with {msg.reply_count} replies")
        for reply in msg.replies:
            print(f"    ↳ {reply.user_id}: {reply.text}")
```

### Error Handling

```python
from slack_ingester import (
    SlackIngester,
    SlackAuthError,
    SlackChannelNotFoundError,
    SlackIngesterError,
    SlackRateLimitError,
)

try:
    ingester = SlackIngester()
    result = await ingester.ingest("C1234567890")
except SlackAuthError:
    print("Invalid or missing Slack bot token")
except SlackChannelNotFoundError:
    print("Channel not found or bot is not a member")
except SlackRateLimitError as e:
    print(f"Rate limited, retry after {e.retry_after} seconds")
except SlackIngesterError as e:
    print(f"Slack API error: {e}")
```

## API Reference

### `SlackIngester`

The main entry point for the library.

#### `__init__(token: str | None = None, *, timeout: float = 60.0) -> None`

Create a new ingester instance.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `token` | `str \| None` | `None` | Slack Bot Token. Falls back to `SLACK_BOT_TOKEN` env var. |
| `timeout` | `float` | `60.0` | HTTP request timeout in seconds. |

Raises `SlackAuthError` if no token is available.

#### `async ingest(channel_id, *, message_ts, thread_ts, oldest, latest, include_replies, max_messages) -> IngestionResult`

Ingest messages from a Slack channel, a specific thread, or a single message.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `channel_id` | `str` | *(required)* | The Slack channel ID to ingest from. |
| `message_ts` | `str \| None` | `None` | Fetch a single message by its timestamp. All other parameters except `channel_id` are ignored. Cannot be combined with `thread_ts`. |
| `thread_ts` | `str \| None` | `None` | Thread timestamp. If set, ingests only that thread (ignores `oldest`, `latest`, `include_replies`). Cannot be combined with `message_ts`. |
| `oldest` | `datetime \| date \| None` | `None` | Only fetch messages newer than this (inclusive). |
| `latest` | `datetime \| date \| None` | `None` | Only fetch messages older than this (inclusive). |
| `include_replies` | `bool` | `True` | Whether to fetch thread replies for parent messages. |
| `max_messages` | `int \| None` | `None` | Maximum number of messages to fetch. `None` means all. |

**Returns:** `IngestionResult`

### Data Models

All models are frozen (immutable) dataclasses with `__slots__` for optimal memory usage.

#### `IngestionResult`

| Field | Type | Description |
|---|---|---|
| `channel_id` | `str` | The channel ID. |
| `channel_name` | `str \| None` | The channel name, if available. |
| `messages` | `tuple[SlackMessage, ...]` | Top-level messages (newest first for channel mode, chronological for thread mode). |
| `total_messages` | `int` | Total count including nested replies. |
| `oldest_ts` | `datetime \| None` | UTC datetime of the oldest message, or `None` if empty. |
| `latest_ts` | `datetime \| None` | UTC datetime of the latest message, or `None` if empty. |

#### `SlackMessage`

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Message timestamp (used as unique ID in Slack). |
| `channel_id` | `str` | Channel this message belongs to. |
| `user_id` | `str \| None` | User ID of the author, or `None` for bot messages without a user. |
| `text` | `str` | Message text content. |
| `timestamp` | `datetime` | UTC datetime of the message. |
| `thread_ts` | `str \| None` | Thread parent timestamp, if this message is part of a thread. |
| `is_thread_parent` | `bool` | `True` if this message started a thread with replies. |
| `reply_count` | `int` | Number of replies in the thread. |
| `replies` | `tuple[SlackMessage, ...]` | Nested reply messages (populated when `include_replies=True`). |
| `files` | `tuple[SlackFile, ...]` | File attachments. |
| `reactions` | `tuple[SlackReaction, ...]` | Emoji reactions. |
| `is_bot` | `bool` | `True` if the message was posted by a bot. |
| `subtype` | `str \| None` | Slack message subtype (e.g., `"bot_message"`). |

#### `SlackFile`

| Field | Type | Description |
|---|---|---|
| `id` | `str` | File ID. |
| `name` | `str` | File name. |
| `mimetype` | `str` | MIME type. |
| `size` | `int` | File size in bytes. |
| `url_private` | `str \| None` | Private download URL (requires authentication). |
| `permalink` | `str \| None` | Permalink to the file in Slack. |

#### `SlackReaction`

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Emoji name (without colons). |
| `count` | `int` | Total reaction count. |
| `users` | `tuple[str, ...]` | User IDs who reacted. |

### Exceptions

All exceptions inherit from `SlackIngesterError`.

| Exception | Description |
|---|---|
| `SlackIngesterError` | Base exception for all library errors. |
| `SlackAuthError` | Invalid, missing, or revoked bot token. |
| `SlackChannelNotFoundError` | Channel not found, bot not in channel, or missing scope. |
| `SlackRateLimitError` | Slack API rate limit hit. Has a `retry_after: int` attribute (seconds). |

## Architecture

```
src/slack_ingester/
├── __init__.py       # Public API exports
├── client.py         # Low-level async Slack API client (httpx)
├── exceptions.py     # Exception hierarchy
├── ingester.py       # High-level ingestion orchestrator
└── models.py         # Immutable data models (frozen dataclasses)
```

### Component Overview

- **`SlackClient`** (`client.py`): Thin async wrapper around the Slack Web API. Handles HTTP requests, response validation, and error mapping. Uses `httpx.AsyncClient` with bearer token authentication. Wraps three Slack endpoints:
  - `conversations.info` - channel metadata
  - `conversations.history` - paginated channel messages
  - `conversations.replies` - paginated thread replies

- **`SlackIngester`** (`ingester.py`): High-level orchestrator that coordinates the client to build a complete `IngestionResult`. Handles pagination loops, date-to-timestamp conversion, concurrent reply fetching via `asyncio.TaskGroup`, and message parsing.

- **Models** (`models.py`): Immutable value objects representing Slack data. All use `@dataclass(slots=True, frozen=True)` for safety and performance.

- **Exceptions** (`exceptions.py`): Structured exception hierarchy mapping Slack API error codes to typed Python exceptions.

### Channel vs. Thread Ingestion

| Aspect | Channel Mode | Thread Mode |
|---|---|---|
| API endpoint | `conversations.history` | `conversations.replies` |
| `oldest` / `latest` | Respected | Ignored |
| `include_replies` | Respected | Ignored (all messages included) |
| `max_messages` | Respected | Respected |
| Message ordering | Newest first | Chronological |
| Reply nesting | Replies nested in parent's `replies` tuple | Flat list of all messages |

## Development

### Prerequisites

- [Python 3.13+](https://www.python.org/)
- [uv](https://docs.astral.sh/uv/) - fast Python package manager
- [just](https://github.com/casey/just) - command runner (optional but recommended)

### Setup

```
git clone https://github.com/gvre/slack-ingester.git
cd slack-ingester

# Install all dependencies (dev + test)
just install-all

# Or manually with uv
uv sync --extra dev --extra test
```

### Available Commands

Run `just` to see all available commands:

| Command | Description |
|---|---|
| `just install` | Install runtime dependencies |
| `just install-dev` | Install development dependencies |
| `just install-all` | Install all dependencies (dev + test) |
| `just test` | Run tests |
| `just test-coverage` | Run tests with terminal coverage report |
| `just test-coverage-html` | Run tests with HTML coverage report |
| `just lint` | Run linting with ruff |
| `just lint-fix` | Auto-fix linting issues |
| `just format` | Format code with ruff |
| `just typecheck` | Run type checking with ty |
| `just check` | Run all checks (lint + typecheck) |
| `just build` | Build the package |
| `just clean` | Remove build artifacts and caches |

### Running Tests

```
# Run all tests
just test

# Run tests with coverage
just test-coverage

# Run a specific test file
uv run pytest tests/test_ingester.py

# Run a specific test class
uv run pytest tests/test_ingester.py::TestIngest

# Run a specific test
uv run pytest tests/test_ingester.py::TestIngest::test_basic_ingest -v
```

### Code Quality

```
# Lint
just lint

# Auto-fix lint issues
just lint-fix

# Format
just format

# Type check
just typecheck

# Run all checks
just check
```

## License

This project is licensed under the [MIT License](LICENSE.md).

Copyright (c) 2026 Giannis Vrentzos
