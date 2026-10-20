"""Channel-aware parser registry for the three configured Telegram channels."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from parser.base_parser import BaseParser
from parser.pipxpert_parser import PipXpertParser
from parser.gold_snipers_parser import GoldSnipersParser
from parser.ben_gold_trader_parser import BenGoldTraderParser

@dataclass(frozen=True)
class ParserProfile:
    key: str
    usernames: tuple[str, ...]
    title_fragments: tuple[str, ...]
    parser: BaseParser

_PROFILES = (
    ParserProfile("pipxpert", ("pipxpert",), ("pipxpert",), PipXpertParser()),
    ParserProfile("gold_snipers", ("goldsnipers11", "gold_snipers"), ("gold snipers",), GoldSnipersParser()),
    ParserProfile("ben_gold_trader", ("bengoldtrader", "ben_gold_trader"), ("ben, gold trader", "ben gold trader"), BenGoldTraderParser()),
)


def _clean(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower().lstrip("@"))


def resolve_parser(channel_username: str | None = None, channel_title: str | None = None) -> BaseParser | None:
    """Resolve by exact configured username first, then by normalized title."""
    username = _clean(channel_username)
    if username:
        for profile in _PROFILES:
            if username in {_clean(item) for item in profile.usernames}:
                return profile.parser
    title = str(channel_title or "").strip().lower()
    if title:
        for profile in _PROFILES:
            if any(fragment in title for fragment in profile.title_fragments):
                return profile.parser
    return None


def parse_for_channel(message: dict[str, Any]):
    """Return (SignalSchema, parser_key); None schema means generic fallback."""
    parser = resolve_parser(message.get("channel_username"), message.get("channel_title"))
    if parser is None:
        return None, None
    text = str(message.get("current_text") or message.get("text") or message.get("raw_text") or message.get("message") or "")
    # Known-channel parser owns classification. Do not let generic parsing
    # reinterpret a profile's non-signal message as a trade signal.
    return parser.parse(message), parser.parser_name
