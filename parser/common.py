"""Shared helpers for channel-specific parsers."""
import re
from typing import Any

from parser.base_parser import BaseParser, extract_number, normalize_text


def symbol_in(text: str) -> str | None:
    if re.search(r"\b(?:XAU\s*/?\s*USD|XAUUSD|GOLD)\b", text, re.I):
        return "XAUUSD"
    for pattern, symbol in (
        (r"\bEUR\s*/?\s*USD\b|\bEURUSD\b", "EURUSD"),
        (r"\bGBP\s*/?\s*USD\b|\bGBPUSD\b", "GBPUSD"),
        (r"\bUSD\s*/?\s*JPY\b|\bUSDJPY\b", "USDJPY"),
    ):
        if re.search(pattern, text, re.I):
            return symbol
    return None


def parse_range(value: str) -> tuple[float | None, float | None, float | None]:
    value = value.replace(",", ".")
    match = re.search(
        r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:-|–|—|\bto\b)\s*(\d+(?:\.\d+)?)(?![\d.])",
        value, re.I
    )
    if match:
        raw_a, raw_b = match.group(1), match.group(2)
        a, b = float(raw_a), float(raw_b)
        # Channel templates often abbreviate the second XAU price (4167-65,
        # 4178-80). Expand it within the first price's leading digits.
        if "." not in raw_a and "." not in raw_b:
            digits_a, digits_b = raw_a, raw_b
            if len(digits_b) < len(digits_a):
                prefix = digits_a[:len(digits_a) - len(digits_b)]
                expanded = float(prefix + digits_b)
                scale = 10 ** len(digits_b)
                if abs(expanded - a) > scale * 2:
                    expanded = float(str(int(a) // scale * scale + int(digits_b)))
                b = expanded
        low, high = min(a, b), max(a, b)
        return (low + high) / 2, low, high
    n = extract_number(value)
    return (n, n, n) if n is not None else (None, None, None)


def extract_tps(text: str, allow_bare_tp: bool = False) -> tuple[float, ...]:
    values: dict[int, float] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(?:🎯\s*)?(?:TP\s*(\d{1,2})|TARGET\s*(\d{1,2})|TAKE\s*PROFIT\s*(\d{1,2}))\s*[:=@-]?\s*(.+?)\s*$", line, re.I)
        if m:
            idx = next(int(x) for x in m.groups()[:3] if x is not None)
            n = extract_number(m.group(4))
            if 1 <= idx <= 10 and n is not None:
                values[idx] = n
            continue
        if allow_bare_tp:
            m = re.match(r"^\s*(?:🎯\s*)?TP\s*[:=@-]?\s*(\d+(?:[.,]\d+)?)\s*$", line, re.I)
            if m:
                values[len(values)+1] = float(m.group(1).replace(",", "."))
    return tuple(values[i] for i in sorted(values))
