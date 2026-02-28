from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from slack_ingester.exceptions import SlackAuthError
from slack_ingester.ingester import SlackIngester, _to_slack_ts
from slack_ingester.models import IngestionResult

CHANNEL_INFO = {"id": "C001", "name": "general"}

RAW_PARENT = {
    "ts": "1700000000.000100",
    "thread_ts": "1700000000.000100",
    "user": "U001",
    "text": "Parent message",
    "reply_count": 1,
}

RAW_SIMPLE = {
    "ts": "1700000001.000200",
    "user": "U002",
    "text": "Simple message",
    "reply_count": 0,
}

RAW_REPLY = {
    "ts": "1700000002.000300",
    "thread_ts": "1700000000.000100",
    "user": "U003",
    "text": "Reply",
    "reply_count": 0,
}


@pytest.fixture
async def ingester(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[SlackIngester]:
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
    async with SlackIngester() as ing:
        yield ing


class TestLifecycle:
    async def test_ingester_aclose_closes_client(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
        ingester = SlackIngester()
        with patch.object(ingester._client, "aclose", new=AsyncMock()) as mock_aclose:
            await ingester.aclose()
            mock_aclose.assert_called_once()

    async def test_ingester_context_manager_calls_aclose_on_exit(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
        ingester = SlackIngester()
        with patch.object(ingester._client, "aclose", new=AsyncMock()) as mock_aclose:
            async with ingester:
                pass
            mock_aclose.assert_called_once()

    async def test_ingester_context_manager_calls_aclose_on_exception(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
        ingester = SlackIngester()
        with patch.object(ingester._client, "aclose", new=AsyncMock()) as mock_aclose:
            with pytest.raises(RuntimeError):
                async with ingester:
                    raise RuntimeError("boom")
            mock_aclose.assert_called_once()

    async def test_ingester_context_manager_returns_self(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
        ingester = SlackIngester()
        with patch.object(ingester._client, "aclose", new=AsyncMock()):
            async with ingester as ctx:
                assert ctx is ingester


class TestSlackIngesterInit:
    def test_raises_without_token(self, monkeypatch):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        with pytest.raises(SlackAuthError):
            SlackIngester()

    def test_explicit_token(self):
        ingester = SlackIngester(token="xoxb-test")
        assert ingester._client is not None

    def test_env_token(self, monkeypatch):
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-env")
        ingester = SlackIngester()
        assert ingester._client is not None


class TestIngest:
    async def test_basic_ingest(self, ingester):
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_channel_history",
                new=AsyncMock(return_value=([RAW_SIMPLE], None)),
            ),
        ):
            result = await ingester.ingest("C001", include_replies=False)

        assert isinstance(result, IngestionResult)
        assert result.channel_id == "C001"
        assert result.channel_name == "general"
        assert len(result.messages) == 1
        assert result.total_messages == 1

    async def test_pagination(self, ingester):
        calls = 0

        async def history_side_effect(
            channel_id: str,
            *,
            oldest: str | None = None,
            latest: str | None = None,
            cursor: str | None = None,
            limit: int = 200,
        ) -> tuple[list[dict[str, Any]], str | None]:
            nonlocal calls
            calls += 1
            if calls == 1:
                return [RAW_SIMPLE], "cursor1"
            return [RAW_PARENT], None

        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_channel_history",
                new=AsyncMock(side_effect=history_side_effect),
            ),
        ):
            result = await ingester.ingest("C001", include_replies=False)

        assert calls == 2
        assert len(result.messages) == 2

    async def test_max_messages(self, ingester):
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_channel_history",
                new=AsyncMock(return_value=([RAW_SIMPLE, RAW_PARENT], None)),
            ),
        ):
            result = await ingester.ingest("C001", max_messages=1, include_replies=False)

        assert len(result.messages) == 1

    async def test_include_replies(self, ingester):
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_channel_history",
                new=AsyncMock(return_value=([RAW_PARENT], None)),
            ),
            patch.object(
                ingester._client,
                "get_thread_messages",
                new=AsyncMock(return_value=[RAW_PARENT, RAW_REPLY]),
            ),
        ):
            result = await ingester.ingest("C001", include_replies=True)

        assert len(result.messages) == 1
        parent = result.messages[0]
        assert parent.is_thread_parent is True
        assert len(parent.replies) == 1
        assert parent.replies[0].user_id == "U003"
        assert result.total_messages == 2

    async def test_include_replies_false(self, ingester):
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_channel_history",
                new=AsyncMock(return_value=([RAW_PARENT], None)),
            ),
        ):
            result = await ingester.ingest("C001", include_replies=False)

        assert result.messages[0].replies == ()

    async def test_oldest_latest_ts(self, ingester):
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_channel_history",
                new=AsyncMock(return_value=([RAW_SIMPLE, RAW_PARENT], None)),
            ),
        ):
            result = await ingester.ingest("C001", include_replies=False)

        # Slack returns newest first; messages[0] is latest, messages[-1] is oldest
        assert result.latest_ts == result.messages[0].timestamp
        assert result.oldest_ts == result.messages[-1].timestamp

    async def test_oldest_as_datetime(self, ingester):
        mock_history = AsyncMock(return_value=([RAW_SIMPLE], None))
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_channel_history",
                new=mock_history,
            ),
        ):
            await ingester.ingest(
                "C001",
                oldest=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
                include_replies=False,
            )
        _, kwargs = mock_history.call_args
        assert kwargs["oldest"] == _to_slack_ts(datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC))

    async def test_latest_as_date(self, ingester):
        mock_history = AsyncMock(return_value=([RAW_SIMPLE], None))
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_channel_history",
                new=mock_history,
            ),
        ):
            await ingester.ingest(
                "C001",
                latest=date(2024, 1, 15),
                include_replies=False,
            )
        _, kwargs = mock_history.call_args
        assert kwargs["latest"] == _to_slack_ts(date(2024, 1, 15), end_of_day=True)

    async def test_oldest_as_date_and_latest_as_datetime(self, ingester):
        mock_history = AsyncMock(return_value=([RAW_SIMPLE], None))
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_channel_history",
                new=mock_history,
            ),
        ):
            await ingester.ingest(
                "C001",
                oldest=date(2024, 1, 1),
                latest=datetime(2024, 1, 15, 23, 59, 59, tzinfo=UTC),
                include_replies=False,
            )
        _, kwargs = mock_history.call_args
        assert kwargs["oldest"] == _to_slack_ts(date(2024, 1, 1))
        assert kwargs["latest"] == _to_slack_ts(datetime(2024, 1, 15, 23, 59, 59, tzinfo=UTC))

    async def test_empty_channel(self, ingester):
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_channel_history",
                new=AsyncMock(return_value=([], None)),
            ),
        ):
            result = await ingester.ingest("C001")

        assert result.messages == ()
        assert result.total_messages == 0
        assert result.oldest_ts is None
        assert result.latest_ts is None


class TestSingleMessageIngestion:
    async def test_ingest_single_message(self, ingester):
        mock_history = AsyncMock(return_value=([RAW_SIMPLE], None))
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_channel_history",
                new=mock_history,
            ),
        ):
            result = await ingester.ingest("C001", message_ts="1700000001.000200")

        assert isinstance(result, IngestionResult)
        assert result.channel_id == "C001"
        assert result.channel_name == "general"
        assert len(result.messages) == 1
        assert result.messages[0].id == "1700000001.000200"
        assert result.messages[0].text == "Simple message"
        assert result.total_messages == 1
        mock_history.assert_called_once_with(
            "C001",
            oldest="1700000001.000200",
            latest="1700000001.000200",
            limit=1,
        )

    async def test_ingest_single_message_not_found(self, ingester):
        mock_history = AsyncMock(return_value=([], None))
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_channel_history",
                new=mock_history,
            ),
        ):
            result = await ingester.ingest("C001", message_ts="9999999999.999999")

        assert result.messages == ()
        assert result.total_messages == 0
        assert result.oldest_ts is None
        assert result.latest_ts is None

    async def test_ingest_single_message_ignores_other_params(self, ingester):
        mock_history = AsyncMock(return_value=([RAW_SIMPLE], None))
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_channel_history",
                new=mock_history,
            ),
        ):
            result = await ingester.ingest(
                "C001",
                message_ts="1700000001.000200",
                oldest=datetime(2024, 1, 1, tzinfo=UTC),
                latest=datetime(2024, 12, 31, tzinfo=UTC),
                include_replies=True,
                max_messages=100,
            )

        # Should fetch single message regardless of other params
        assert len(result.messages) == 1
        mock_history.assert_called_once_with(
            "C001",
            oldest="1700000001.000200",
            latest="1700000001.000200",
            limit=1,
        )

    async def test_ingest_single_message_with_thread_ts_raises(self, ingester):
        with pytest.raises(ValueError, match="Cannot specify both message_ts and thread_ts"):
            await ingester.ingest(
                "C001",
                message_ts="1700000001.000200",
                thread_ts="1700000000.000100",
            )


class TestToSlackTs:
    def test_datetime_with_utc(self):
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        result = _to_slack_ts(dt)
        assert result == f"{dt.timestamp():.6f}"
        assert float(result) == dt.timestamp()

    def test_naive_datetime_assumed_utc(self):
        naive = datetime(2024, 1, 15, 10, 30, 0)
        aware = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        assert _to_slack_ts(naive) == _to_slack_ts(aware)

    def test_datetime_with_non_utc_timezone(self):
        eastern = timezone(-timedelta(hours=5))
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=eastern)
        result = _to_slack_ts(dt)
        # 10:30 EST = 15:30 UTC
        expected = datetime(2024, 1, 15, 15, 30, 0, tzinfo=UTC)
        assert float(result) == pytest.approx(expected.timestamp())

    def test_date_start_of_day(self):
        d = date(2024, 1, 15)
        result = _to_slack_ts(d)
        expected = datetime(2024, 1, 15, 0, 0, 0, tzinfo=UTC)
        assert float(result) == expected.timestamp()

    def test_date_end_of_day(self):
        d = date(2024, 1, 15)
        result = _to_slack_ts(d, end_of_day=True)
        expected = datetime(2024, 1, 15, 23, 59, 59, 999999, tzinfo=UTC)
        assert float(result) == pytest.approx(expected.timestamp())

    def test_date_end_of_day_is_after_start_of_day(self):
        d = date(2024, 1, 15)
        start = float(_to_slack_ts(d))
        end = float(_to_slack_ts(d, end_of_day=True))
        assert end > start

    def test_result_format_has_six_decimal_places(self):
        dt = datetime(2024, 1, 15, 0, 0, 0, tzinfo=UTC)
        result = _to_slack_ts(dt)
        integer_part, decimal_part = result.split(".")
        assert len(decimal_part) == 6

    def test_end_of_day_false_is_same_as_default(self):
        d = date(2024, 6, 1)
        assert _to_slack_ts(d) == _to_slack_ts(d, end_of_day=False)


class TestThreadIngestion:
    async def test_ingest_thread(self, ingester):
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_thread_messages",
                new=AsyncMock(return_value=[RAW_PARENT, RAW_REPLY]),
            ),
        ):
            result = await ingester.ingest("C001", thread_ts="1700000000.000100")

        assert isinstance(result, IngestionResult)
        assert result.channel_id == "C001"
        assert result.channel_name == "general"
        assert len(result.messages) == 2
        assert result.messages[0].id == "1700000000.000100"
        assert result.messages[1].id == "1700000002.000300"
        assert result.total_messages == 2

    async def test_ingest_thread_with_max_messages(self, ingester):
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_thread_messages",
                new=AsyncMock(return_value=[RAW_PARENT, RAW_REPLY]),
            ),
        ):
            result = await ingester.ingest("C001", thread_ts="1700000000.000100", max_messages=1)

        assert len(result.messages) == 1
        assert result.messages[0].id == "1700000000.000100"

    async def test_ingest_thread_ignores_oldest_latest(self, ingester):
        mock_thread = AsyncMock(return_value=[RAW_PARENT, RAW_REPLY])
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_thread_messages",
                new=mock_thread,
            ),
        ):
            result = await ingester.ingest(
                "C001",
                thread_ts="1700000000.000100",
                oldest=datetime(2024, 1, 1, tzinfo=UTC),
                latest=datetime(2024, 12, 31, tzinfo=UTC),
            )

        # Should fetch thread regardless of oldest/latest
        assert len(result.messages) == 2
        mock_thread.assert_called_once_with("C001", "1700000000.000100")

    async def test_ingest_thread_ignores_include_replies(self, ingester):
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_thread_messages",
                new=AsyncMock(return_value=[RAW_PARENT, RAW_REPLY]),
            ),
        ):
            result = await ingester.ingest(
                "C001",
                thread_ts="1700000000.000100",
                include_replies=False,
            )

        # Thread ingestion always includes all messages
        assert len(result.messages) == 2

    async def test_ingest_thread_rejects_message_ts_combination(self, ingester):
        with pytest.raises(ValueError, match="Cannot specify both message_ts and thread_ts"):
            await ingester.ingest(
                "C001",
                message_ts="1700000001.000200",
                thread_ts="1700000000.000100",
            )

    async def test_ingest_thread_empty(self, ingester):
        with (
            patch.object(
                ingester._client,
                "get_channel_info",
                new=AsyncMock(return_value=CHANNEL_INFO),
            ),
            patch.object(
                ingester._client,
                "get_thread_messages",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await ingester.ingest("C001", thread_ts="1700000000.000100")

        assert result.messages == ()
        assert result.total_messages == 0
        assert result.oldest_ts is None
        assert result.latest_ts is None
