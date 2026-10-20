"""Parser for PipXpert (pipxpert).

Separates actionable, structured signal posts from market alerts and outcome
updates. Only a complete direction/entry/SL/TP template is backtest eligible.
"""
from __future__ import annotations
import re
from typing import Any
from parser.base_parser import BaseParser, extract_number, normalize_text
from parser.common import parse_range, extract_tps

class PipXpertParser(BaseParser):
    parser_name = "pipxpert"
    parser_version = "1.0.0"
    supported_symbols = ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY")

    _SYMBOLS = (
        (r"\b(?:XAU\s*/?\s*USD|XAUUSD|GOLD)\b", "XAUUSD"),
        (r"\b(?:EUR\s*/?\s*USD|EURUSD)\b", "EURUSD"),
        (r"\b(?:GBP\s*/?\s*USD|GBPUSD)\b", "GBPUSD"),
        (r"\b(?:USD\s*/?\s*JPY|USDJPY)\b", "USDJPY"),
    )

    def can_parse(self, text: str) -> bool:
        t = normalize_text(text)
        if not t: return False
        has_symbol = any(re.search(p, t, re.I) for p, _ in self._SYMBOLS)
        structured = bool(re.search(r"(?im)^\s*Direction\s*:\s*(?:BUY|SELL)\s*$", t)
                          and re.search(r"(?im)^\s*Entry\s*Price\s*:", t)
                          and re.search(r"(?im)^\s*SL\s+", t))
        alert = bool(re.search(r"(?i)\bmarket alert\b", t) and has_symbol)
        return has_symbol and (structured or alert)

    def parse_fields(self, text: str) -> dict[str, Any]:
        t = normalize_text(text)
        symbol = next((s for p, s in self._SYMBOLS if re.search(p, t, re.I)), None)
        if re.search(r"(?i)\bmarket alert\b", t):
            bias = re.search(r"(?im)^\s*Current market bias\s*:\s*(Bullish|Bearish)\s*$", t)
            levels = re.findall(r"(?m)^\s*(\d+(?:\.\d+)?)\s*-\s*(?:first|deeper|extended)\b", t, re.I)
            invalidation = re.search(r"(?i)invalidation area:\s*(?:\n.*?near\s*)?(\d+(?:\.\d+)?)", t, re.S)
            return {
                "category": "MARKET_ALERT", "symbol": symbol,
                "direction": ("BUY" if bias and bias.group(1).lower()=="bullish" else "SELL" if bias else None),
                "validation_flags": [], "backtest_eligible": False, "confidence": 0.85,
                "metadata": {"profile": self.parser_name, "market_bias": bias.group(1).upper() if bias else None,
                             "market_alert_levels": [float(x) for x in levels],
                             "invalidation_level": float(invalidation.group(1)) if invalidation else None},
            }
        fields: dict[str, Any] = {
            "category": "REJECTED_SIGNAL", "symbol": symbol, "direction": None,
            "entry": None, "entry_min": None, "entry_max": None, "stop_loss": None,
            "take_profits": (), "validation_flags": [], "backtest_eligible": False,
            "confidence": 0.0, "metadata": {"profile": self.parser_name, "template": "Direction/Entry Price/TP1../SL"},
        }
        d = re.search(r"(?im)^\s*Direction\s*:\s*(BUY|SELL)\s*$", t)
        if d: fields["direction"] = d.group(1).upper()
        ent = re.search(r"(?im)^\s*Entry\s*Price\s*:\s*([^\n]+)", t)
        if ent:
            entry, low, high = parse_range(ent.group(1))
            fields.update(entry=entry, entry_min=low, entry_max=high)
        sl = re.search(r"(?im)^\s*SL\s*[:=@-]?\s*([^\n]+)", t)
        if sl: fields["stop_loss"] = extract_number(sl.group(1))
        fields["take_profits"] = extract_tps(t)
        missing = []
        for key, flag in (("direction","direction_missing"),("entry","entry_missing"),
                          ("stop_loss","stop_loss_missing"),("take_profits","take_profit_missing")):
            if not fields[key]: missing.append(flag)
        fields["validation_flags"] = missing
        fields["category"] = "TRADE_SIGNAL" if not missing else "REJECTED_SIGNAL"
        fields["confidence"] = 0.98 if not missing else 0.3
        fields["backtest_eligible"] = not missing
        return fields

def parse_pipxpert_message(message):
    return PipXpertParser().parse(message)
