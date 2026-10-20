#!/usr/bin/env python3
"""Rule-based parser for Telegram trade-signal messages.

The parser can read legacy JSON exports or process raw_messages from the shared
SQLite database. It performs deterministic parsing only: no AI and no OCR.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from database.connection import database_connection, database_transaction

PARSER_VERSION = "0.6.0-channel-parsers"

try:
    from parser.registry import parse_for_channel
except ImportError:  # Supports running a copied script before parser package installation.
    parse_for_channel = None
logger = logging.getLogger("parse_signals")

NUM_RE = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?")
SYMBOL_PATTERNS = [
    (r"\b(?:XAU\s*/?\s*USD|GOLD)\b", "XAUUSD"),
    (r"\bEUR\s*/?\s*USD\b", "EURUSD"),
    (r"\bGBP\s*/?\s*USD\b", "GBPUSD"),
    (r"\bUSD\s*/?\s*JPY\b", "USDJPY"),
    (r"\bUSD\s*/?\s*CHF\b", "USDCHF"),
    (r"\bAUD\s*/?\s*USD\b", "AUDUSD"),
    (r"\bNZD\s*/?\s*USD\b", "NZDUSD"),
    (r"\bUSD\s*/?\s*CAD\b", "USDCAD"),
    (r"\bEUR\s*/?\s*(?:GBP|JPY|CHF|AUD|CAD)\b", None),
    (r"\bGBP\s*/?\s*(?:JPY|CHF|AUD|CAD)\b", None),
]


def num(value: str) -> float:
    return float(value.replace(",", "."))


def expand_range(a: str, b: str) -> tuple[float, float]:
    """Expand shorthand ranges such as 4178-80 and normalize their order."""
    a, b = a.replace(",", "."), b.replace(",", ".")
    if "." in a or "." in b:
        av, bv = num(a), num(b)
        return min(av, bv), max(av, bv)

    av = int(a)
    if len(b) < len(a):
        scale = 10 ** len(b)
        bv = (av // scale) * scale + int(b)
        if bv < av:
            bv += scale
    else:
        bv = int(b)
    return float(min(av, bv)), float(max(av, bv))


def parse_price_or_range(value: str) -> tuple[float | None, float | None, float | None]:
    value = value.strip().replace(",", ".")
    match = re.search(
        r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d+(?:\.\d+)?)(?!\d)",
        value,
        re.I,
    )
    if match:
        low, high = expand_range(match.group(1), match.group(2))
        return (low + high) / 2, low, high

    match = NUM_RE.search(value)
    if not match:
        return None, None, None
    price = num(match.group())
    return price, price, price


def extract_fields(text: str) -> dict[str, Any]:
    symbol = None
    for pattern, normalized in SYMBOL_PATTERNS:
        match = re.search(pattern, text, re.I)
        if match:
            symbol = normalized or re.sub(r"\s|/", "", match.group()).upper()
            break

    direction = None
    match = re.search(r"\bDirection\s*:\s*(BUY|SELL)\b", text, re.I)
    if not match:
        match = re.search(
            r"(?im)^\s*(?:(?:📣|📊|🔔|⚡|⭐|[-•])\s*)?"
            r"(?:XAU\s*/?\s*USD|GOLD|EUR\s*/?\s*USD|GBP\s*/?\s*USD|USD\s*/?\s*JPY)?"
            r"\s*(BUY|SELL)\b",
            text,
        )
    if match:
        direction = match.group(1).upper()

    if not direction:
        match = re.search(
            r"(?im)^\s*(BUY|SELL)\s+"
            r"(?:GOLD|XAU\s*/?\s*USD|EUR\s*/?\s*USD|GBP\s*/?\s*USD|USD\s*/?\s*JPY)\b",
            text,
        )
        if match:
            direction = match.group(1).upper()

    entry = entry_min = entry_max = None
    match = re.search(
        r"(?im)^\s*(?:📍\s*)?ENTRY(?:\s*PRICE)?\s*[:=@-]?\s*([^\n]+)",
        text,
    )
    if not match:
        match = re.search(r"(?im)^\s*Entry(?:\s*Price)?\s+([^\n]+)", text)
    if match:
        entry, entry_min, entry_max = parse_price_or_range(match.group(1))
    else:
        match = re.search(
            r"(?im)^\s*(?:BUY|SELL)\s+"
            r"(?:GOLD|XAU\s*/?\s*USD|EUR\s*/?\s*USD|GBP\s*/?\s*USD|USD\s*/?\s*JPY)"
            r"\s*@\s*([^\n]+)",
            text,
        )
        if match:
            entry, entry_min, entry_max = parse_price_or_range(match.group(1))

    stop_loss = None
    match = re.search(
        r"(?im)^\s*(?:🛑\s*)?(?:SL|STOP\s*LOSS)\s*[:=@-]?\s*([^\n]+)",
        text,
    )
    if match:
        stop_loss, _, _ = parse_price_or_range(match.group(1))

    take_profits: dict[str, float] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*(?:🎯\s*)?TP\s*(.*?)\s*$", line, re.I)
        if not match:
            match = re.match(r"^\s*(?:TAKE\s*PROFIT)\s*(.*?)\s*$", line, re.I)
        if not match:
            continue

        rest = match.group(1).strip().lstrip(":=@- ").strip()
        if not rest:
            continue

        explicit = re.match(r"^(\d{1,2})\s*[:=]\s*(\d+(?:[.,]\d+)?)\b", rest)
        if not explicit:
            explicit = re.match(r"^(\d{1,2})\s+(\d+(?:[.,]\d+)?)\s*$", rest)

        if explicit and 1 <= int(explicit.group(1)) <= 10:
            index, price = int(explicit.group(1)), num(explicit.group(2))
        else:
            price_match = NUM_RE.search(rest)
            if not price_match:
                continue
            price = num(price_match.group())
            index = max([int(key[2:]) for key in take_profits] or [0]) + 1

        take_profits[f"tp{index}"] = price

    return {
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "entry_min": entry_min,
        "entry_max": entry_max,
        "take_profits": take_profits,
        "stop_loss": stop_loss,
    }


def core_complete(fields: dict[str, Any]) -> bool:
    return (
        fields.get("direction") in {"BUY", "SELL"}
        and fields.get("entry") is not None
        and fields.get("stop_loss") is not None
        and bool(fields.get("take_profits"))
    )


def looks_like_signal(text: str, fields: dict[str, Any]) -> bool:
    if core_complete(fields):
        return True
    cues = [
        r"\bENTRY(?:\s*PRICE)?\b",
        r"\bSTOP\s*LOSS\b",
        r"(?m)^\s*SL\s*[:=@-]",
        r"(?m)^\s*TP\s*\d*\s*[:=@-]?\s*\d",
        r"\bTAKE\s*PROFIT\b",
    ]
    return sum(bool(re.search(pattern, text, re.I)) for pattern in cues) >= 2 or (
        fields.get("direction") in {"BUY", "SELL"} and bool(re.search(r"@\s*\d", text))
    )


def classify(message: dict[str, Any]) -> tuple[str, dict[str, Any], list[str]]:
    text = (
        message.get("current_text")
        or message.get("text")
        or message.get("raw_text")
        or message.get("message")
        or ""
    ).strip()
    fields = extract_fields(text)
    reasons: list[str] = []

    if not text:
        category = "NEEDS_REVIEW" if message.get("has_media") else "OTHER"
        reasons.append("empty_text_ignored_media" if message.get("has_media") else "empty_text")
    elif core_complete(fields):
        if not fields.get("symbol"):
            reasons.append("symbol_missing")
        entry = fields["entry"]
        values = [
            fields["take_profits"][key]
            for key in sorted(fields["take_profits"], key=lambda key: int(key[2:]))
        ]
        if fields["direction"] == "BUY":
            if fields["stop_loss"] >= fields.get("entry_min", entry):
                reasons.append("buy_sl_not_below_entry_zone")
            if any(value <= fields.get("entry_max", entry) for value in values):
                reasons.append("buy_tp_not_above_entry_zone")
            if any(values[i] > values[i + 1] for i in range(len(values) - 1)):
                reasons.append("buy_tp_order_nonascending")
        else:
            if fields["stop_loss"] <= fields.get("entry_max", entry):
                reasons.append("sell_sl_not_above_entry_zone")
            if any(value >= fields.get("entry_min", entry) for value in values):
                reasons.append("sell_tp_not_below_entry_zone")
            if any(values[i] < values[i + 1] for i in range(len(values) - 1)):
                reasons.append("sell_tp_order_non_descending")
        if len(set(values)) != len(values):
            reasons.append("duplicate_tp_price")
        category = "TRADE_SIGNAL" if not reasons else "REJECTED_SIGNAL"
    elif looks_like_signal(text, fields):
        category = "REJECTED_SIGNAL"
        if fields.get("direction") not in {"BUY", "SELL"}:
            reasons.append("direction_missing_or_ambiguous")
        if fields.get("entry") is None:
            reasons.append("entry_missing_or_ambiguous")
        if fields.get("stop_loss") is None:
            reasons.append("stop_loss_missing_or_ambiguous")
        if not fields.get("take_profits"):
            reasons.append("take_profit_missing_or_ambiguous")
        reasons.append("excluded_from_backtest")
    elif re.search(r"\bmarket\s*alert\b", text, re.I):
        category = "MARKET_ALERT"
    elif re.search(
        r"\b(?:move\s+(?:the\s+)?SL|SL\s+to\s+(?:entry|break.?even)|break.?even|"
        r"cancel(?:led|ed)?\s+(?:the\s+)?signal|position\s+(?:is\s+)?still\s+running|"
        r"close\s+(?:the\s+)?trade)\b",
        text,
        re.I,
    ):
        category = "TRADE_UPDATE"
    elif re.search(
        r"\b(?:hit\s*TP\s*\d|reached\s*TP\s*\d|TP\s*\d\s*(?:hit|reached|done)|"
        r"hit\s+(?:SL|stop\s*loss)|\bSL\s+(?:hit|reached)|closed\s+(?:in\s+)?profit|"
        r"\+\s*\d+\s*pips|secured\s+\+?\d+\s*pips|\d+/\d+\s+TPs?)\b",
        text,
        re.I,
    ):
        category = "RESULT_REPORT"
    elif re.search(
        r"\b(?:join\s+VIP|inside\s+VIP|VIP channel|subscribe|join us|free VIP spots)\b",
        text,
        re.I,
    ):
        category = "PROMOTION"
    elif re.search(
        r"\b(?:support|resistance|market bias|volatility|CPI|NFP|PCE|GDP|news release|"
        r"market analysis|invalidation area|timeframes reviewed)\b",
        text,
        re.I,
    ):
        category = "MARKET_ANALYSIS"
    else:
        category = "OTHER"

    return category, fields, list(dict.fromkeys(reasons))


def _message_row(message: dict[str, Any], source_file: str = "") -> dict[str, Any]:
    """Normalize one message using its dedicated channel parser when available."""
    current_text = (
        message.get("current_text")
        or message.get("text")
        or message.get("raw_text")
        or message.get("message")
        or ""
    )
    parsed = None
    parser_name = "generic_rules"
    if parse_for_channel is not None:
        parsed, resolved_name = parse_for_channel({**message, "current_text": current_text})
        if parsed is not None:
            parser_name = resolved_name or parsed.parser_name

    if parsed is not None:
        data = parsed.to_dict()
        tp_values = list(data.get("take_profits") or [])
        take_profits = {f"tp{i}": value for i, value in enumerate(tp_values, start=1)}
        category = data.get("category", "OTHER")
        flags = list(data.get("validation_flags") or [])
        backtest_eligible = bool(data.get("backtest_eligible")) and not flags
        if message.get("collection_status") == "edited" or message.get("edit_date"):
            category = "REJECTED_SIGNAL"
            flags.append("source_message_edited")
            flags = list(dict.fromkeys(flags))
            backtest_eligible = False
        fields = {
            "symbol": data.get("symbol"),
            "direction": data.get("direction"),
            "entry": data.get("entry"),
            "entry_min": data.get("entry_min"),
            "entry_max": data.get("entry_max"),
            "take_profits": take_profits,
            "stop_loss": data.get("stop_loss"),
        }
        extraction_method = data.get("extraction_method", "rules")
        parser_version = data.get("parser_version", PARSER_VERSION)
        confidence = data.get("confidence", 0.0)
    else:
        category, fields, flags = classify(message)
        backtest_eligible = category == "TRADE_SIGNAL" and not flags
        extraction_method = "rules"
        parser_version = PARSER_VERSION
        confidence = 1.0 if backtest_eligible else 0.0
        if message.get("collection_status") == "edited" or message.get("edit_date"):
            category = "REJECTED_SIGNAL" if category in {"TRADE_SIGNAL", "REJECTED_SIGNAL"} else category
            flags = list(dict.fromkeys([*flags, "source_message_edited"]))
            backtest_eligible = False

    return {
        "parser_version": parser_version,
        "parser_name": parser_name,
        "source_file": source_file,
        "raw_message_id": message.get("id") or message.get("raw_message_id"),
        "telegram_message_id": message.get("telegram_message_id") or message.get("message_id"),
        "channel_id": message.get("channel_id"),
        "message_date": message.get("message_date") or message.get("date_utc") or message.get("date") or message.get("date_local"),
        "edit_date": message.get("edit_date") or message.get("edit_date_utc"),
        "channel_username": message.get("channel_username"),
        "channel_title": message.get("channel_title"),
        "category": category,
        **fields,
        "validation_flags": flags,
        "backtest_eligible": backtest_eligible,
        "extraction_method": extraction_method,
        "confidence": confidence,
        "has_media": bool(message.get("has_media")),
        "current_text": current_text,
    }


def load_messages(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, list):
        messages = data
    elif isinstance(data, dict):
        messages = data.get("messages", [])
    else:
        messages = []
    if not isinstance(messages, list) or any(not isinstance(item, dict) for item in messages):
        raise ValueError(f"Invalid JSON export structure: {path}")
    return messages


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_database(limit: int | None = None, channel_id: int | None = None) -> dict[str, Any]:
    """Parse raw_messages and persist trade-like results to the signals tables.

    Only TRADE_SIGNAL and REJECTED_SIGNAL rows are persisted. Non-signal posts
    remain available in raw_messages and are counted in the returned summary.
    Edited source messages are marked ambiguous, so they are not backtest-ready.
    """
    query = """
        SELECT rm.*, c.username AS channel_username, c.title AS channel_title
        FROM raw_messages AS rm
        JOIN channels AS c ON c.id = rm.channel_id
    """
    params: list[Any] = []
    if channel_id is not None:
        query += " WHERE rm.channel_id = ?"
        params.append(channel_id)
    query += " ORDER BY rm.message_date, rm.id"
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be positive.")
        query += " LIMIT ?"
        params.append(limit)

    with database_connection() as connection:
        raw_messages = [dict(row) for row in connection.execute(query, params).fetchall()]

    counts: Counter[str] = Counter()
    persisted = 0
    now = _utc_now()

    with database_transaction() as connection:
        for raw in raw_messages:
            row = _message_row(raw)
            category = row["category"]
            counts[category] += 1
            raw_message_id = int(raw["id"])
            existing = connection.execute(
                "SELECT * FROM signals WHERE raw_message_id = ? AND signal_index = 0",
                (raw_message_id,),
            ).fetchone()
            edited_source = raw.get("collection_status") == "edited" or bool(raw.get("edit_date"))

            # Critical edit safety: if an edited message no longer parses as a
            # signal, its previously stored signal must still be invalidated.
            if category not in {"TRADE_SIGNAL", "REJECTED_SIGNAL"}:
                if existing and edited_source:
                    signal_id = int(existing["id"])
                    connection.execute(
                        "UPDATE signals SET validation_status='ambiguous', confidence=0, updated_at=? WHERE id=?",
                        (now, signal_id),
                    )
                    previous_version = connection.execute(
                        "SELECT COALESCE(MAX(version_number), 0) AS n FROM signal_versions WHERE signal_id=?",
                        (signal_id,),
                    ).fetchone()
                    version_number = int(previous_version["n"]) + 1
                    snapshot = {
                        "parser_version": row.get("parser_version", PARSER_VERSION),
                        "parser_name": row.get("parser_name", "generic_rules"),
                        "category": category,
                        "source_message_edited": True,
                        "backtest_eligible": False,
                        "validation_flags": list(dict.fromkeys([*(row.get("validation_flags") or []), "source_message_edited", "edited_message_no_longer_signal"])),
                        "current_text": row.get("current_text", ""),
                    }
                    connection.execute(
                        """INSERT INTO signal_versions (
                            signal_id, version_number, source_message_edit_date,
                            direction, entry_min, entry_max, stop_loss, take_profit_1,
                            take_profit_2, take_profit_3, snapshot_json, recorded_at,
                            is_original, notes
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                        (signal_id, version_number, raw.get("edit_date"), existing["direction"],
                         existing["entry_min"], existing["entry_max"], existing["stop_loss"],
                         existing["take_profit_1"], existing["take_profit_2"], existing["take_profit_3"],
                         json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now,
                         "source_message_edited;edited_message_no_longer_signal"),
                    )
                continue

            take_profits = row["take_profits"]
            tp1 = take_profits.get("tp1")
            tp2 = take_profits.get("tp2")
            tp3 = take_profits.get("tp3")
            status = "valid" if row["backtest_eligible"] else "invalid"
            if raw.get("collection_status") == "edited" or raw.get("edit_date"):
                status = "ambiguous"

            instrument = row.get("symbol") or "XAUUSD"
            published_at = row.get("message_date") or now
            extracted_at = now
            values = (
                instrument,
                row.get("direction"),
                "ZONE" if row.get("entry_min") != row.get("entry_max") else "UNKNOWN",
                row.get("entry_min"),
                row.get("entry_max"),
                row.get("stop_loss"),
                tp1,
                tp2,
                tp3,
                status,
                1.0 if status == "valid" else 0.0,
                published_at,
                extracted_at,
                now,
            )

            if existing:
                signal_id = int(existing["id"])
                connection.execute(
                    """
                    UPDATE signals SET instrument=?, direction=?, entry_type=?,
                        entry_min=?, entry_max=?, stop_loss=?, take_profit_1=?,
                        take_profit_2=?, take_profit_3=?, extraction_method='rules',
                        validation_status=?, confidence=?, published_at=?,
                        extracted_at=?, updated_at=?
                    WHERE id=?
                    """,
                    (*values, signal_id),
                )
                version_row = connection.execute(
                    "SELECT COALESCE(MAX(version_number), 0) AS n FROM signal_versions WHERE signal_id=?",
                    (signal_id,),
                ).fetchone()
                version_number = int(version_row["n"]) + 1
                is_original = 0
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO signals (
                        raw_message_id, signal_index, instrument, direction, entry_type,
                        entry_min, entry_max, stop_loss, take_profit_1, take_profit_2,
                        take_profit_3, extraction_method, validation_status, confidence,
                        published_at, extracted_at, created_at, updated_at
                    ) VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'rules', ?, ?, ?, ?, ?, ?)
                    """,
                    (raw_message_id, *values, now),
                )
                signal_id = int(cursor.lastrowid)
                version_number = 1
                is_original = 1

            snapshot = {
                "parser_version": row.get("parser_version", PARSER_VERSION),
                "parser_name": row.get("parser_name", "generic_rules"),
                "confidence": row.get("confidence", 0.0),
                "category": category,
                "instrument": instrument,
                "direction": row.get("direction"),
                "entry_min": row.get("entry_min"),
                "entry_max": row.get("entry_max"),
                "stop_loss": row.get("stop_loss"),
                "take_profit_1": tp1,
                "take_profit_2": tp2,
                "take_profit_3": tp3,
                "validation_status": status,
                "validation_flags": row["validation_flags"],
                "backtest_eligible": bool(row["backtest_eligible"]) and status == "valid",
            }
            connection.execute(
                """
                INSERT INTO signal_versions (
                    signal_id, version_number, source_message_edit_date,
                    direction, entry_min, entry_max, stop_loss, take_profit_1,
                    take_profit_2, take_profit_3, snapshot_json, recorded_at,
                    is_original, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_id,
                    version_number,
                    raw.get("edit_date"),
                    row.get("direction"),
                    row.get("entry_min"),
                    row.get("entry_max"),
                    row.get("stop_loss"),
                    tp1,
                    tp2,
                    tp3,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now,
                    is_original,
                    ";".join(row["validation_flags"]) or None,
                ),
            )
            persisted += 1

    return {
        "parser_version": PARSER_VERSION,
        "source_message_count": len(raw_messages),
        "category_counts": dict(sorted(counts.items())),
        "persisted_signal_rows": persisted,
        "channel_id": channel_id,
    }


def process_json(input_path: Path, out_path: Path, csv_path: Path) -> dict[str, Any]:
    sources = (
        sorted(path for path in input_path.glob("*.json") if path.is_file())
        if input_path.is_dir()
        else [input_path]
    )
    if not sources:
        raise SystemExit(f"No JSON files found in: {input_path}")

    results: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    per_source: dict[str, Any] = {}
    for file_path in sources:
        messages = load_messages(file_path)
        file_results = [_message_row(message, file_path.name) for message in messages]
        file_counts = Counter(row["category"] for row in file_results)
        results.extend(file_results)
        counts.update(file_counts)
        per_source[file_path.name] = {
            "source_message_count": len(messages),
            "category_counts": dict(sorted(file_counts.items())),
            "backtest_eligible_signals": sum(bool(row["backtest_eligible"]) for row in file_results),
        }

    output = {
        "parser_version": PARSER_VERSION,
        "source_files": [path.name for path in sources],
        "source_message_count": len(results),
        "category_counts": dict(sorted(counts.items())),
        "backtest_eligible_signals": sum(bool(row["backtest_eligible"]) for row in results),
        "per_source": per_source,
        "messages": results,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    fieldnames = [
        "source_file", "raw_message_id", "telegram_message_id", "channel_id",
        "message_date", "edit_date", "channel_username", "channel_title", "category",
        "symbol", "direction", "entry", "entry_min", "entry_max", "take_profits",
        "stop_loss", "validation_flags", "backtest_eligible", "extraction_method",
        "has_media", "current_text",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            row = dict(result)
            row["take_profits"] = json.dumps(row["take_profits"], ensure_ascii=False)
            row["validation_flags"] = ";".join(row["validation_flags"])
            writer.writerow({key: row.get(key) for key in fieldnames})

    return {
        "parser_version": PARSER_VERSION,
        "source_message_count": len(results),
        "category_counts": dict(sorted(counts.items())),
        "backtest_eligible_signals": output["backtest_eligible_signals"],
        "json_output": str(out_path),
        "csv_output": str(csv_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        action="store_true",
        help="Read raw_messages from the configured SQLite database and persist parsed signals.",
    )
    parser.add_argument("--channel-id", type=int, help="Limit database processing to this local channel ID.")
    parser.add_argument("--limit", type=int, help="Maximum number of database messages to process.")
    parser.add_argument(
        "input",
        nargs="?",
        default="data/json exports",
        help="Legacy JSON file or directory (ignored when --database is set).",
    )
    parser.add_argument("--out", default="data/exports/parsed_signals.json")
    parser.add_argument("--csv", default="data/exports/parsed_signals.csv")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.database:
        summary = process_database(limit=args.limit, channel_id=args.channel_id)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    source = Path(args.input)
    if not source.exists():
        raise SystemExit(f"Input path not found: {source}")
    summary = process_json(source, Path(args.out), Path(args.csv))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
