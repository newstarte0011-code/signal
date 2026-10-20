"""Parser for the GOLD Snipers channel (goldsnipers11).

Recognizes the channel's XAUUSD BUY/SELL + ENTRY range + SL + repeated TP
template. TP-hit/result posts are not mistaken for new entry signals.
"""
from __future__ import annotations
import re
from typing import Any
from parser.base_parser import BaseParser, extract_number, normalize_text
from parser.common import parse_range

class GoldSnipersParser(BaseParser):
    parser_name = "gold_snipers"
    parser_version = "1.0.0"
    supported_symbols = ("XAUUSD",)

    def can_parse(self, text: str) -> bool:
        t = normalize_text(text)
        has_header = bool(re.search(r"(?im)^\s*(?:XAU\s*/?\s*USD|XAUUSD|GOLD)\s+(?:BUY|SELL)\b", t))
        has_entry = bool(re.search(r"(?im)^\s*ENTRY\s*[:=@-]?", t))
        has_sl = bool(re.search(r"(?im)^\s*(?:SL|S/L|STOP\s*LOSS)\s*[:=@-]?", t))
        has_tp = bool(re.search(r"(?im)^\s*TP\s*(?:\d+\s*[:=@-]\s*\d|[:=@-]\s*\d|\d+(?:[.,]\d+)?)", t))
        return (has_header or has_entry) and has_sl and has_tp

    def parse_fields(self, text: str) -> dict[str, Any]:
        t = normalize_text(text)
        fields: dict[str, Any] = {
            "category": "REJECTED_SIGNAL", "symbol": "XAUUSD",
            "direction": None, "entry": None, "entry_min": None, "entry_max": None,
            "stop_loss": None, "take_profits": (), "validation_flags": [],
            "backtest_eligible": False, "confidence": 0.0,
            "metadata": {"profile": self.parser_name, "template": "XAUUSD BUY/SELL; ENTRY; SL; repeated TP"},
        }
        d = re.search(r"(?i)\b(BUY|SELL)\b", t)
        if d: fields["direction"] = d.group(1).upper()
        ent = re.search(r"(?im)^\s*ENTRY\s*[:=@-]?\s*([^\n]+)", t)
        if ent:
            entry, low, high = parse_range(ent.group(1))
            fields.update(entry=entry, entry_min=low, entry_max=high)
        else:
            # Older GOLD Snipers posts use two lines: "GOLD SELL 4360" and
            # "MORE SELL 4370" instead of a single ENTRY range.
            first = re.search(r"(?im)^\s*(?:GOLD|XAUUSD|XAU\s*/?\s*USD)\s+(?:BUY|SELL)\s+(\d+(?:[.,]\d+)?)\s*$", t)
            more = re.search(r"(?im)^\s*MORE\s+(?:BUY|SELL)\s+(\d+(?:[.,]\d+)?)\s*$", t)
            if first:
                a = float(first.group(1).replace(",", "."))
                if more:
                    b = float(more.group(1).replace(",", "."))
                    fields.update(entry=(a+b)/2, entry_min=min(a,b), entry_max=max(a,b))
                else:
                    fields.update(entry=a, entry_min=a, entry_max=a)
        sl = re.search(r"(?im)^\s*(?:SL|S/L|STOP\s*LOSS)\s*[:=@-]?\s*([^\n]+)", t)
        if sl: fields["stop_loss"] = extract_number(sl.group(1))
        tps = []
        for line in t.splitlines():
            # Numbered form: TP1: 4172. Unnumbered form: TP 4172.
            m = re.match(r"^\s*TP\s*\d{1,2}\s*[:=@-]\s*(\d+(?:[.,]\d+)?)\s*$", line, re.I)
            if m:
                tps.append(float(m.group(1).replace(",", ".")))
                continue
            m = re.match(r"^\s*TP\s*[:=@-]?\s*(\d+(?:[.,]\d+)?)\s*$", line, re.I)
            if m:
                tps.append(float(m.group(1).replace(",", ".")))
        fields["take_profits"] = tuple(tps)
        missing = []
        for key, flag in (("direction","direction_missing"),("entry","entry_missing"),
                          ("stop_loss","stop_loss_missing"),("take_profits","take_profit_missing")):
            if not fields[key]: missing.append(flag)
        fields["validation_flags"] = missing
        fields["category"] = "TRADE_SIGNAL" if not missing else "REJECTED_SIGNAL"
        fields["confidence"] = 0.97 if not missing else 0.3
        fields["backtest_eligible"] = not missing
        return fields

def parse_gold_snipers_message(message):
    return GoldSnipersParser().parse(message)
