"""
Telegram channels used by the signal analyzer.

For each channel:
- username: public username without @, or None
- telegram_id: numeric Telegram channel ID, or None

At least one of username or telegram_id must be provided.
"""

CHANNELS = [
    {
        "name": "PipXpert - Forex Signals",
        "username": "pipxpert",
        "telegram_id": -1001818766678,
    },
    {
        "name": "GOLD Snipers",
        "username": "goldsnipers11",
        "telegram_id": -1001584939836,
    },
    {
        "name": "Ben, Gold Trader",
        "username": "bengoldtrader",
        "telegram_id": -1001765226347,
    },

    # نمونهٔ کانالی که یوزرنیمش را نداریم:
    # {
    #     "name": "My Private Channel",
    #     "username": None,
    #     "telegram_id": 1234567890,
    # },
]

# Keep these constants for compatibility with existing tests and code.
TEST_CHANNEL = "pipxpert"
TEST_MESSAGE_LIMIT = 500


def get_channel_reference(channel: dict) -> str | int:
    """
    Return the preferred Telegram reference.

    Username is preferred when available.
    Otherwise, use the numeric Telegram ID.
    """
    username = channel.get("username")
    telegram_id = channel.get("telegram_id")

    if username:
        return username.lstrip("@")

    if telegram_id is not None:
        return int(telegram_id)

    raise ValueError(
        f"Channel {channel.get('name', '<unnamed>')!r} "
        "must have a username or telegram_id."
    )


def validate_channels(channels: list[dict] | None = None) -> None:
    """Validate channel configuration and reject duplicate references."""
    channels = CHANNELS if channels is None else channels
    seen = set()

    for index, channel in enumerate(channels):
        if not isinstance(channel, dict):
            raise TypeError(f"Channel at index {index} must be a dictionary.")

        if not channel.get("username") and channel.get("telegram_id") is None:
            raise ValueError(
                f"Channel at index {index} needs a username or telegram_id."
            )

        username = channel.get("username")
        if username:
            username = username.lstrip("@")
            if not username:
                raise ValueError(
                    f"Channel at index {index} has an empty username."
                )

        telegram_id = channel.get("telegram_id")
        if telegram_id is not None:
            try:
                telegram_id = int(telegram_id)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid telegram_id at channel index {index}."
                ) from exc

        reference = (
            ("username", username.lower())
            if username
            else ("telegram_id", telegram_id)
        )

        if reference in seen:
            raise ValueError(
                f"Duplicate channel reference at index {index}: {reference}"
            )

        seen.add(reference)


validate_channels()