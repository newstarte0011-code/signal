"""Canonical data models for parsed Telegram trading signals.

This module intentionally uses only the Python standard library so that parser
profiles can share a stable schema without adding runtime dependencies.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

Direction = Literal["BUY", "SELL"]
SignalCategory = Literal[
    "TRADE_SIGNAL",
    "REJECTED_SIGNAL",
    "TRADE_UPDATE",
    "RESULT_REPORT",
    "MARKET_ANALYSIS",
    "MARKET_ALERT",
    "PROMOTION",
    "NEEDS_REVIEW",
    "OTHER",
]


def _as_optional_float(value: Any, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(str(value).replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number or None.") from exc
    return result


@dataclass(frozen=True, slots=True)
class SignalSchema:
    """Normalized parser result, whether complete or requiring review."""

    category: SignalCategory = "OTHER"
    symbol: str | None = None
    direction: Direction | None = None
    entry: float | None = None
    entry_min: float | None = None
    entry_max: float | None = None
    stop_loss: float | None = None
    take_profits: tuple[float, ...] = ()
    validation_flags: tuple[str, ...] = ()
    backtest_eligible: bool = False
    extraction_method: str = "rules"
    parser_name: str = "base"
    parser_version: str = "1.0"
    confidence: float = 0.0
    raw_text: str = ""
    source_channel_id: int | None = None
    source_message_id: int | None = None
    message_date: str | None = None
    edit_date: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.direction not in (None, "BUY", "SELL"):
            raise ValueError("direction must be BUY, SELL, or None.")

        for field_name in ("entry", "entry_min", "entry_max", "stop_loss"):
            value = _as_optional_float(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, value)

        normalized_tps = tuple(
            _as_optional_float(value, "take_profits")
            for value in self.take_profits
        )
        if any(value is None for value in normalized_tps):
            raise ValueError("take_profits cannot contain None or empty values.")
        object.__setattr__(self, "take_profits", normalized_tps)

        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0.")

        if self.backtest_eligible and self.category != "TRADE_SIGNAL":
            raise ValueError(
                "Only a TRADE_SIGNAL can be marked backtest_eligible."
            )

        if self.entry_min is not None and self.entry_max is not None:
            if self.entry_min > self.entry_max:
                raise ValueError("entry_min cannot be greater than entry_max.")

        if self.message_date:
            _validate_iso_datetime(self.message_date, "message_date")
        if self.edit_date:
            _validate_iso_datetime(self.edit_date, "edit_date")

    @property
    def is_complete(self) -> bool:
        return (
            self.category == "TRADE_SIGNAL"
            and self.direction in ("BUY", "SELL")
            and self.entry is not None
            and self.stop_loss is not None
            and bool(self.take_profits)
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["take_profits"] = list(self.take_profits)
        result["validation_flags"] = list(self.validation_flags)
        return result

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "SignalSchema":
        """Build a schema from a mapping, accepting common legacy field names."""
        take_profits = data.get("take_profits", ())
        if isinstance(take_profits, dict):
            def tp_key(item: tuple[str, Any]) -> tuple[int, str]:
                key = item[0].lower().replace("tp", "")
                try:
                    return int(key), item[0]
                except ValueError:
                    return 999, item[0]
            take_profits = [
                value for _, value in sorted(take_profits.items(), key=tp_key)
            ]
        if take_profits is None:
            take_profits = ()
        if not isinstance(take_profits, (list, tuple)):
            raise ValueError("take_profits must be a list, tuple, or TP mapping.")

        flags = data.get("validation_flags", data.get("flags", ()))
        if flags is None:
            flags = ()
        if isinstance(flags, str):
            flags = (flags,)
        if not isinstance(flags, (list, tuple)):
            raise ValueError("validation_flags must be a list, tuple, or string.")

        entry = data.get("entry")
        entry_min = data.get("entry_min")
        entry_max = data.get("entry_max")
        if entry is None and entry_min is not None and entry_max is not None:
            entry = (float(entry_min) + float(entry_max)) / 2
        elif entry is None:
            entry = data.get("entry_price")

        category = data.get("category", "TRADE_SIGNAL" if data.get("direction") else "OTHER")
        if category not in {
            "TRADE_SIGNAL", "REJECTED_SIGNAL", "TRADE_UPDATE", "RESULT_REPORT",
            "MARKET_ANALYSIS", "MARKET_ALERT", "PROMOTION", "NEEDS_REVIEW", "OTHER",
        }:
            raise ValueError(f"Unsupported signal category: {category!r}")

        return cls(
            category=category,
            symbol=data.get("symbol", data.get("instrument")),
            direction=data.get("direction"),
            entry=entry,
            entry_min=entry_min,
            entry_max=entry_max,
            stop_loss=data.get("stop_loss", data.get("sl")),
            take_profits=tuple(take_profits),
            validation_flags=tuple(str(flag) for flag in flags),
            backtest_eligible=bool(data.get("backtest_eligible", False)),
            extraction_method=str(data.get("extraction_method", "rules")),
            parser_name=str(data.get("parser_name", "base")),
            parser_version=str(data.get("parser_version", "1.0")),
            confidence=float(data.get("confidence", 0.0)),
            raw_text=str(data.get("raw_text", data.get("current_text", data.get("text", ""))) or ""),
            source_channel_id=data.get("source_channel_id", data.get("channel_id")),
            source_message_id=data.get("source_message_id", data.get("telegram_message_id")),
            message_date=data.get("message_date"),
            edit_date=data.get("edit_date"),
            metadata=dict(data.get("metadata") or {}),
        )


def _validate_iso_datetime(value: str, field_name: str) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 datetime string.") from exc


def validate_signal(signal: SignalSchema) -> tuple[str, ...]:
    """Return validation problems without raising for ordinary invalid signals."""
    problems: list[str] = list(signal.validation_flags)

    if signal.category != "TRADE_SIGNAL":
        if signal.backtest_eligible:
            problems.append("non_trade_signal_marked_backtest_eligible")
        return tuple(dict.fromkeys(problems))

    if not signal.symbol:
        problems.append("symbol_missing")
    if signal.direction not in ("BUY", "SELL"):
        problems.append("direction_missing_or_invalid")
    if signal.entry is None or signal.entry_min is None or signal.entry_max is None:
        problems.append("entry_missing")
    if signal.stop_loss is None:
        problems.append("stop_loss_missing")
    if not signal.take_profits:
        problems.append("take_profit_missing")

    if signal.direction == "BUY" and signal.stop_loss is not None:
        entry_floor = signal.entry_min if signal.entry_min is not None else signal.entry
        if entry_floor is not None and signal.stop_loss >= entry_floor:
            problems.append("buy_sl_not_below_entry_zone")
    if signal.direction == "SELL" and signal.stop_loss is not None:
        entry_ceiling = signal.entry_max if signal.entry_max is not None else signal.entry
        if entry_ceiling is not None and signal.stop_loss <= entry_ceiling:
            problems.append("sell_sl_not_above_entry_zone")

    if signal.direction == "BUY" and signal.take_profits:
        entry_ceiling = signal.entry_max if signal.entry_max is not None else signal.entry
        if entry_ceiling is not None and any(tp <= entry_ceiling for tp in signal.take_profits):
            problems.append("buy_tp_not_above_entry_zone")
        if any(a > b for a, b in zip(signal.take_profits, signal.take_profits[1:])):
            problems.append("buy_tp_order_nonascending")
    elif signal.direction == "SELL" and signal.take_profits:
        entry_floor = signal.entry_min if signal.entry_min is not None else signal.entry
        if entry_floor is not None and any(tp >= entry_floor for tp in signal.take_profits):
            problems.append("sell_tp_not_below_entry_zone")
        if any(a < b for a, b in zip(signal.take_profits, signal.take_profits[1:])):
            problems.append("sell_tp_order_non_descending")

    if len(set(signal.take_profits)) != len(signal.take_profits):
        problems.append("duplicate_tp_price")

    return tuple(dict.fromkeys(problems))
