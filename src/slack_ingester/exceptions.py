class SlackIngesterError(Exception):
    """Base exception for slack-ingester."""


class SlackAuthError(SlackIngesterError):
    """Raised when the bot token is invalid or missing."""


class SlackChannelNotFoundError(SlackIngesterError):
    """Raised when the channel is not found or not accessible."""


class SlackRateLimitError(SlackIngesterError):
    """Raised when the Slack API rate limit is hit."""

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after
