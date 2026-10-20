"""Fixture test for stage 9 parser dispatch; no Telegram login or DB required."""
from __future__ import annotations
import argparse, json
from collections import Counter
from pathlib import Path
from parser.registry import parse_for_channel

PROFILES = {
    "pipxpert": ("PipXpert - Forex Signals", "pipxpert"),
    "gold_snipers": ("GOLD Snipers", "goldsnipers11"),
    "ben_gold_trader": ("Ben, Gold Trader", "bengoldtrader"),
}
EXPECTED = {
    "pipxpert": {"TRADE_SIGNAL": 118, "MARKET_ALERT": 78, "REJECTED_SIGNAL": 2},
    "gold_snipers": {"TRADE_SIGNAL": 29, "REJECTED_SIGNAL": 2},
    "ben_gold_trader": {"TRADE_SIGNAL": 11},
}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pipxpert", required=True)
    ap.add_argument("--gold-snipers", required=True)
    ap.add_argument("--ben-gold-trader", required=True)
    args = ap.parse_args()
    inputs = {"pipxpert": args.pipxpert, "gold_snipers": args.gold_snipers, "ben_gold_trader": args.ben_gold_trader}
    report = {}
    for key, filename in inputs.items():
        payload = json.loads(Path(filename).read_text(encoding="utf-8-sig"))
        messages = payload if isinstance(payload, list) else payload.get("messages", [])
        title, username = PROFILES[key]
        counts = Counter()
        eligible = 0
        for item in messages:
            message = {**item, "channel_title": title, "channel_username": username}
            parsed, resolved = parse_for_channel(message)
            assert parsed is not None and resolved is not None, f"No parser selected for {key}"
            counts[parsed.category] += 1
            eligible += bool(parsed.backtest_eligible)
        for category, expected_count in EXPECTED[key].items():
            assert counts[category] == expected_count, (key, category, counts[category], expected_count)
        report[key] = {"messages": len(messages), "categories": dict(sorted(counts.items())), "backtest_eligible": eligible}
    print(json.dumps(report, indent=2, ensure_ascii=False))

if __name__ == "__main__": main()
