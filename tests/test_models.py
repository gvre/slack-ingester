from datetime import UTC, datetime

import pytest

from slack_ingester.ingester import _parse_file, _parse_message, _parse_reaction, _ts_to_datetime


class TestTsToDatetime:
    def test_basic_conversion(self):
        dt = _ts_to_datetime("1700000000.000000")
        assert isinstance(dt, datetime)
        assert dt.tzinfo is UTC

    def test_value(self):
        dt = _ts_to_datetime("0.000000")
        assert dt == datetime(1970, 1, 1, tzinfo=UTC)

    def test_fractional(self):
        dt = _ts_to_datetime("1700000000.123456")
        assert dt.tzinfo is UTC
        assert abs(dt.timestamp() - 1700000000.123456) < 0.001


class TestParseReaction:
    def test_basic(self):
        raw = {"name": "thumbsup", "count": 3, "users": ["U1", "U2", "U3"]}
        reaction = _parse_reaction(raw)
        assert reaction.name == "thumbsup"
        assert reaction.count == 3
        assert reaction.users == ("U1", "U2", "U3")

    def test_empty_users(self):
        raw = {"name": "heart", "count": 0, "users": []}
        reaction = _parse_reaction(raw)
        assert reaction.users == ()

    def test_missing_fields(self):
        reaction = _parse_reaction({})
        assert reaction.name == ""
        assert reaction.count == 0
        assert reaction.users == ()


class TestParseFile:
    def test_basic(self):
        raw = {
            "id": "F001",
            "name": "photo.png",
            "mimetype": "image/png",
            "size": 2048,
            "url_private": "https://files.slack.com/photo.png",
            "permalink": "https://workspace.slack.com/files/photo.png",
        }
        f = _parse_file(raw)
        assert f.id == "F001"
        assert f.name == "photo.png"
        assert f.mimetype == "image/png"
        assert f.size == 2048
        assert f.url_private == "https://files.slack.com/photo.png"
        assert f.permalink == "https://workspace.slack.com/files/photo.png"

    def test_missing_optional_urls(self):
        raw = {"id": "F002", "name": "file.txt", "mimetype": "text/plain", "size": 100}
        f = _parse_file(raw)
        assert f.url_private is None
        assert f.permalink is None

    def test_empty_url_coerced_to_none(self):
        raw = {
            "id": "F003",
            "name": "x",
            "mimetype": "text/plain",
            "size": 0,
            "url_private": "",
            "permalink": "",
        }
        f = _parse_file(raw)
        assert f.url_private is None
        assert f.permalink is None


class TestParseMessage:
    def test_regular_message(self, raw_message):
        msg = _parse_message(raw_message, "C001")
        assert msg.id == "1700000000.000100"
        assert msg.channel_id == "C001"
        assert msg.user_id == "U12345"
        assert msg.text == "Hello, world!"
        assert msg.is_thread_parent is True
        assert msg.reply_count == 2
        assert msg.is_bot is False
        assert msg.subtype is None
        assert len(msg.reactions) == 1
        assert len(msg.files) == 1

    def test_bot_message(self, raw_bot_message):
        msg = _parse_message(raw_bot_message, "C001")
        assert msg.is_bot is True
        assert msg.subtype == "bot_message"
        assert msg.user_id is None
        assert msg.is_thread_parent is False

    def test_slackbot_message(self, raw_slackbot_message):
        msg = _parse_message(raw_slackbot_message, "C001")
        assert msg.is_bot is True
        assert msg.user_id == "USLACKBOT"
        assert msg.subtype is None

    def test_reply_message(self, raw_reply):
        msg = _parse_message(raw_reply, "C001")
        assert msg.thread_ts == "1700000000.000100"
        assert msg.id != msg.thread_ts
        assert msg.is_thread_parent is False

    def test_with_replies_attached(self, raw_message, raw_reply):
        reply_msg = _parse_message(raw_reply, "C001")
        parent = _parse_message(raw_message, "C001", replies=(reply_msg,))
        assert len(parent.replies) == 1
        assert parent.replies[0].user_id == "U67890"

    def test_immutable(self, raw_message):
        msg = _parse_message(raw_message, "C001")
        with pytest.raises((AttributeError, TypeError)):
            msg.text = "modified"  # type: ignore[misc]
