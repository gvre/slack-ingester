from typing import Any

import pytest


@pytest.fixture
def raw_message() -> dict[str, Any]:
    return {
        "ts": "1700000000.000100",
        "thread_ts": "1700000000.000100",
        "user": "U12345",
        "text": "Hello, world!",
        "reply_count": 2,
        "reactions": [{"name": "thumbsup", "count": 3, "users": ["U1", "U2", "U3"]}],
        "files": [
            {
                "id": "F001",
                "name": "doc.pdf",
                "mimetype": "application/pdf",
                "size": 1024,
                "url_private": "https://files.slack.com/doc.pdf",
                "permalink": "https://workspace.slack.com/files/doc.pdf",
            }
        ],
    }


@pytest.fixture
def raw_bot_message() -> dict[str, Any]:
    return {
        "ts": "1700000001.000200",
        "bot_id": "B001",
        "subtype": "bot_message",
        "text": "Automated update",
        "reply_count": 0,
    }


@pytest.fixture
def raw_slackbot_message() -> dict[str, Any]:
    return {
        "ts": "1700000003.000400",
        "user": "USLACKBOT",
        "text": "I searched for that channel and it seems like it doesn't exist.",
        "reply_count": 0,
    }


@pytest.fixture
def raw_reply() -> dict[str, Any]:
    return {
        "ts": "1700000002.000300",
        "thread_ts": "1700000000.000100",
        "user": "U67890",
        "text": "I agree!",
        "reply_count": 0,
    }
