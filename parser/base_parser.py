"""Reusable base classes and helpers for channel-specific signal parsers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, Iterable

from parser.signal_schema import SignalSchema, validate_signal

BASE_PARSER_VERSION = "1.0"


class BaseParser(ABC):
    """Base contract for deterministic parsers.

    Implement ``parse_fields`` in each channel parser. The base class handles
    normalization, common validation, and source metadata consistently.
    """

    parser_name = "base"
    parser_version = BASE_PARSER_VERSION
    supported_symbols: tuple[str, ...] = ("XAUUSD",)

    @abstractmethod
    def parse_fields(self, text: str) -> dict[str, Any]:
        """Extract parser-specific fields from message text."""

    def can_parse(self, text: str) -> bool:
        """Return whether the text contains enough cues for this parser."""
        normalized = normalize_text(text)
        if not normalized:
            return False
        if re.search(r"\b(?:BUY|SELL)\b", normalized, re.I):
            return True
        return bool(re.search(r"\b(?:ENTRY|STOP\s*LOSS|TAKE\s*PROFIT|TP\d*)\b", normalized, re.I))

    def parse(self, message: dict[str, Any] | str) -> SignalSchema:
        """Parse a message or plain text and return a canonical schema object."""
        if isinstance(message, str):
            source: dict[str, Any] = {"text": message}
        elif isinstance(message, dict):
            source = message
        else:
            raise TypeError("message must be a string or dictionary.")

        text = str(
            source.get("current_text")
            or source.get("text")
            or source.get("raw_text")
            or source.get("message")
            or ""
        )
        if not self.can_parse(text):
            return SignalSchema(
                category="OTHER",
                parser_name=self.parser_name,
                parser_version=self.parser_version,
                raw_text=text,
                source_channel_id=source.get("channel_id"),
                source_message_id=source.get("telegram_message_id") or source.get("message_id"),
                message_date=source.get("message_date") or source.get("date"),
                edit_date=source.get("edit_date"),
            )

        extracted = dict(self.parse_fields(text) or {})
        extracted.setdefault("category", "TRADE_SIGNAL")
        extracted.setdefault("extraction_method", "rules")
        extracted.setdefault("parser_name", self.parser_name)
        extracted.setdefault("parser_version", self.parser_version)
        extracted.setdefault("raw_text", text)
        extracted.setdefault("source_channel_id", source.get("channel_id"))
        extracted.setdefault(
            "source_message_id",
            source.get("telegram_message_id") or source.get("message_id"),
        )
        extracted.setdefault("message_date", source.get("message_date") or source.get("date"))
        extracted.setdefault("edit_date", source.get("edit_date"))

        # Edited source messages are deliberately excluded from backtesting
        # until an explicit signal-version review workflow approves them.
        flags = list(extracted.get("validation_flags") or ())
        edited = bool(source.get("edit_date")) or source.get("collection_status") == "edited"
        if edited:
            flags.append("source_message_edited")
            extracted["category"] = "REJECTED_SIGNAL"
            extracted["backtest_eligible"] = False
        extracted["validation_flags"] = tuple(dict.fromkeys(flags))

        signal = SignalSchema.from_mapping(extracted)
        validation_problems = validate_signal(signal)
        if validation_problems != signal.validation_flags:
            # Rebuild with all validator findings, without changing the extracted values.
            updated = signal.to_dict()
            updated["validation_flags"] = list(validation_problems)
            if validation_problems and updated["category"] == "TRADE_SIGNAL":
                updated["category"] = "REJECTED_SIGNAL"
                updated["backtest_eligible"] = False
            signal = SignalSchema.from_mapping(updated)
        elif signal.category == "TRADE_SIGNAL" and not signal.validation_flags:
            # A parser must explicitly opt into backtesting only when the signal
            # is complete and passes the shared checks.
            signal = SignalSchema.from_mapping(
                {**signal.to_dict(), "backtest_eligible": signal.is_complete}
            )
        return signal

    @classmethod
    def normalize_symbol(cls, value: str | None) -> str | None:
        """Normalize common gold/forex symbol spellings."""
        if not value:
            return None
        compact = re.sub(r"[\s/_-]+", "", value).upper()
        aliases = {
            "GOLD": "XAUUSD",
            "XAU": "XAUUSD",
            "XAUUS": "XAUUSD",
            "XAUUSD.": "XAUUSD",
        }
        compact = aliases.get(compact, compact)
        if not re.fullmatch(r"[A-Z]{6}", compact):
            return None
        return compact


def normalize_text(text: str) -> str:
    """Normalize whitespace and common Unicode punctuation without losing lines."""
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def first_match(patterns: Iterable[str], text: str, flags: int = re.IGNORECASE) -> re.Match[str] | None:
    """Return the first regex match from an ordered collection of patterns."""
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match
    return None


def extract_number(value: str) -> float | None:
    """Extract the first decimal number from text; comma decimals are supported."""
    match = re.search(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?", value)
    if not match:
        return None
    try:
        return float(match.group().replace(",", "."))
    except ValueError:
        return None
