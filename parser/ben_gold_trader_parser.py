"""Parser for the Ben, Gold Trader public channel (bengoldtrader).

Only messages with an explicit Gold entry zone, stop-loss, and at least one
target are treated as trade signals. Follow-up/scalping chatter and results
are intentionally not converted into entry signals.
"""
from __future__ import annotations
import re
from typing import Any
from parser.base_parser import BaseParser, extract_number, normalize_text
from parser.common import parse_range, extract_tps

class BenGoldTraderParser(BaseParser):
    parser_name = "ben_gold_trader"
    parser_version = "1.0.0"
    supported_symbols = ("XAUUSD",)

    def can_parse(self, text: str) -> bool:
        t = normalize_text(text)
        has_setup = bool(re.search(r"(?im)^\s*(?:buy|sell)\s+(?:gold|xau/?usd)\b.*@", t))
        has_entry = bool(re.search(r"(?im)^\s*entry(?:\s*price)?\s*[:=@-]", t))
        return bool((has_setup or has_entry)
                    and re.search(r"(?im)^\s*(?:sl|s/l|stop\s*loss)\s*[:=@-]", t)
                    and re.search(r"(?im)^\s*(?:tp\s*\d*|target\s*\d+)\s*[:=@-]?", t))

    def parse_fields(self, text: str) -> dict[str, Any]:
        t = normalize_text(text)
        fields: dict[str, Any] = {
            "category": "REJECTED_SIGNAL", "symbol": "XAUUSD",
            "direction": None, "entry": None, "entry_min": None, "entry_max": None,
            "stop_loss": None, "take_profits": (), "validation_flags": [],
            "backtest_eligible": False, "confidence": 0.0,
            "metadata": {"profile": self.parser_name, "template": "Buy/Sell Gold @zone; Sl; Tp1/Tp2"},
        }
        direction = re.search(r"(?i)\b(BUY|SELL)\s+(?:GOLD|XAU/?USD)\b", t)
        if direction:
            fields["direction"] = direction.group(1).upper()
        entry_match = re.search(r"(?im)^\s*(?:BUY|SELL)\s+(?:GOLD|XAU/?USD)\s*@\s*([^\n]+)", t)
        if not entry_match:
            entry_match = re.search(r"(?im)^\s*ENTRY(?:\s*PRICE)?\s*[:=@-]\s*([^\n]+)", t)
        if entry_match:
            entry, low, high = parse_range(entry_match.group(1))
            fields.update(entry=entry, entry_min=low, entry_max=high)
        sl = re.search(r"(?im)^\s*(?:SL|S/L|STOP\s*LOSS)\s*[:=@-]?\s*([^\n]+)", t)
        if sl:
            fields["stop_loss"] = extract_number(sl.group(1))
        fields["take_profits"] = extract_tps(t, allow_bare_tp=True)
        missing = []
        for key, flag in (("direction","direction_missing"),("entry","entry_missing"),
                          ("stop_loss","stop_loss_missing"),("take_profits","take_profit_missing")):
            if not fields[key]: missing.append(flag)
        fields["validation_flags"] = missing
        fields["category"] = "TRADE_SIGNAL" if not missing else "REJECTED_SIGNAL"
        fields["confidence"] = 0.96 if not missing else 0.3
        fields["backtest_eligible"] = not missing
        return fields

def parse_ben_gold_trader_message(message):
    return BenGoldTraderParser().parse(message)
