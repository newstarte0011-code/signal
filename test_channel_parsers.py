"""Regression-check the channel parsers against Telegram JSON exports.

Usage:
python test_channel_parsers.py "PipXpert - Forex Signals.json" "GOLD Snipers.json" "Ben, Gold Trader.json"
Run from project root after installing the parser files.
"""
import json
import sys
from collections import Counter
from pathlib import Path

from parser.pipxpert_parser import PipXpertParser
from parser.gold_snipers_parser import GoldSnipersParser
from parser.ben_gold_trader_parser import BenGoldTraderParser

def check(path, parser):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    counts = Counter()
    examples = []
    for item in data.get("messages", []):
        text = item.get("text") or item.get("raw_text") or ""
        if not parser.can_parse(text):
            continue
        result = parser.parse({
            "text": text,
            "telegram_message_id": item.get("telegram_message_id"),
            "channel_id": data.get("channel_telegram_id"),
        })
        counts[result.category] += 1
        if result.category == "TRADE_SIGNAL":
            examples.append({
                "message_id": result.source_message_id,
                "symbol": result.symbol,
                "direction": result.direction,
                "entry_min": result.entry_min,
                "entry_max": result.entry_max,
                "sl": result.stop_loss,
                "tps": list(result.take_profits),
                "backtest_eligible": result.backtest_eligible,
            })
    print(f"{data.get('channel_config_name')}: {len(data.get('messages', []))} messages scanned")
    print(f"Matched categories: {dict(counts)}")
    print("First parsed signals:")
    for example in examples[:3]:
        print(" ", example)
    print()
    return counts, examples

def main():
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    checks = [
        (sys.argv[1], PipXpertParser()),
        (sys.argv[2], GoldSnipersParser()),
        (sys.argv[3], BenGoldTraderParser()),
    ]
    for path, parser in checks:
        check(path, parser)

if __name__ == "__main__":
    main()
