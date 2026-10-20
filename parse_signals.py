#!/usr/bin/env python3
"""Rule-based parser for exported Telegram trade-signal messages (no AI, no OCR)."""
from __future__ import annotations
import argparse, csv, json, re
from collections import Counter
from pathlib import Path

PARSER_VERSION = "0.4.0"
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

def num(s):
    return float(s.replace(',', '.'))

def expand_range(a, b):
    """Expand shorthand ranges like 4178-80 and normalize descending ranges."""
    a, b = a.replace(',', '.'), b.replace(',', '.')
    if '.' in a or '.' in b:
        av, bv = num(a), num(b)
        return min(av, bv), max(av, bv)
    av = int(a)
    if len(b) < len(a):
        bv = (av // (10 ** len(b))) * (10 ** len(b)) + int(b)
        if bv < av:
            bv += 10 ** len(b)
    else:
        bv = int(b)
    return float(min(av, bv)), float(max(av, bv))

def parse_price_or_range(s):
    s = s.strip().replace(',', '.')
    m = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*(\d+(?:\.\d+)?)(?!\d)", s, re.I)
    if m:
        lo, hi = expand_range(m.group(1), m.group(2))
        return (lo + hi) / 2, lo, hi
    m = NUM_RE.search(s)
    if not m:
        return None, None, None
    v = num(m.group())
    return v, v, v

def extract_fields(text):
    symbol = None
    for pattern, normalized in SYMBOL_PATTERNS:
        m = re.search(pattern, text, re.I)
        if m:
            symbol = normalized or re.sub(r"\s|/", "", m.group()).upper()
            break

    # Direction should be taken from the signal header/field, not promotional prose.
    direction = None
    m = re.search(r"\bDirection\s*:\s*(BUY|SELL)\b", text, re.I)
    if not m:
        m = re.search(r"(?im)^\s*(?:(?:📣|📊|🔔|⚡|⭐|[-•])\s*)?(?:XAU\s*/?\s*USD|GOLD|EUR\s*/?\s*USD|GBP\s*/?\s*USD|USD\s*/?\s*JPY)?\s*(BUY|SELL)\b", text)
    if m:
        direction = m.group(1).upper()
    if not direction:
        # Common Ben format: "Buy Gold @4177.2-4167.2"
        m = re.search(r"(?im)^\s*(BUY|SELL)\s+(?:GOLD|XAU\s*/?\s*USD|EUR\s*/?\s*USD|GBP\s*/?\s*USD|USD\s*/?\s*JPY)\b", text)
        if m:
            direction = m.group(1).upper()

    entry = entry_min = entry_max = None
    # Explicit Entry label, allowing a zone/range such as 4178-80 or 4167-65.
    m = re.search(r"(?im)^\s*(?:📍\s*)?ENTRY(?:\s*PRICE)?\s*[:=@-]?\s*([^\n]+)", text)
    if not m:
        m = re.search(r"(?im)^\s*Entry(?:\s*Price)?\s+([^\n]+)", text)
    if m:
        entry, entry_min, entry_max = parse_price_or_range(m.group(1))
    else:
        # Ben-style entries: Buy Gold @4177.2-4167.2
        m = re.search(r"(?im)^\s*(?:BUY|SELL)\s+(?:GOLD|XAU\s*/?\s*USD|EUR\s*/?\s*USD|GBP\s*/?\s*USD|USD\s*/?\s*JPY)\s*@\s*([^\n]+)", text)
        if m:
            entry, entry_min, entry_max = parse_price_or_range(m.group(1))

    sl = None
    m = re.search(r"(?im)^\s*(?:🛑\s*)?(?:SL|STOP\s*LOSS)\s*[:=@-]?\s*([^\n]+)", text)
    if m:
        sl, _, _ = parse_price_or_range(m.group(1))

    # Parse each TP line by line. A lone number after TP is a price, not a TP index.
    # This fixes the old bug where "TP 4173" was interpreted as TP4=173.
    tps = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(?:🎯\s*)?TP\s*(.*?)\s*$", line, re.I)
        if not m:
            m = re.match(r"^\s*(?:TAKE\s*PROFIT)\s*(.*?)\s*$", line, re.I)
        if not m:
            continue
        rest = m.group(1).strip().lstrip(':=@- ').strip()
        if not rest:
            continue
        # Explicit forms: TP1 4181, TP 1: 4181, TP1:4181.
        explicit = re.match(r"^(\d{1,2})\s*[:=]\s*(\d+(?:[.,]\d+)?)\b", rest)
        if not explicit:
            explicit = re.match(r"^(\d{1,2})\s+(\d+(?:[.,]\d+)?)\s*$", rest)
        if explicit and 1 <= int(explicit.group(1)) <= 10:
            idx, price = int(explicit.group(1)), num(explicit.group(2))
        else:
            pm = NUM_RE.search(rest)
            if not pm:
                continue
            price = num(pm.group())
            idx = max([int(k[2:]) for k in tps] or [0]) + 1
        tps[f"tp{idx}"] = price

    return {"symbol": symbol, "direction": direction, "entry": entry,
            "entry_min": entry_min, "entry_max": entry_max,
            "take_profits": tps, "stop_loss": sl}

def core_complete(f):
    return (f.get("direction") in {"BUY", "SELL"} and f.get("entry") is not None
            and f.get("stop_loss") is not None and bool(f.get("take_profits")))

def looks_like_signal(text, fields):
    if core_complete(fields):
        return True
    # Avoid classifying a result/marketing post as an incomplete trade signal just
    # because it mentions BUY/SELL, TP or SL in passing.
    cues = [r"\bENTRY(?:\s*PRICE)?\b", r"\bSTOP\s*LOSS\b", r"(?m)^\s*SL\s*[:=@-]",
            r"(?m)^\s*TP\s*\d*\s*[:=@-]?\s*\d", r"\bTAKE\s*PROFIT\b"]
    return sum(bool(re.search(p, text, re.I)) for p in cues) >= 2 or (
        fields.get("direction") in {"BUY", "SELL"} and bool(re.search(r"@\s*\d", text)))

def classify(message):
    text = (message.get("current_text") or message.get("text") or message.get("raw_text") or message.get("message") or "").strip()
    fields = extract_fields(text)
    reasons = []
    if not text:
        category = "NEEDS_REVIEW" if message.get("has_media") else "OTHER"
        reasons.append("empty_text_ignored_media" if message.get("has_media") else "empty_text")
    elif core_complete(fields):
        if not fields.get("symbol"):
            reasons.append("symbol_missing")
        entry = fields["entry"]
        vals = [fields["take_profits"][k] for k in sorted(fields["take_profits"], key=lambda x: int(x[2:]))]
        if fields["direction"] == "BUY":
            if fields["stop_loss"] >= fields.get("entry_min", entry): reasons.append("buy_sl_not_below_entry_zone")
            if any(v <= fields.get("entry_max", entry) for v in vals): reasons.append("buy_tp_not_above_entry_zone")
            if any(vals[i] > vals[i+1] for i in range(len(vals)-1)): reasons.append("buy_tp_order_nonascending")
        else:
            if fields["stop_loss"] <= fields.get("entry_max", entry): reasons.append("sell_sl_not_above_entry_zone")
            if any(v >= fields.get("entry_min", entry) for v in vals): reasons.append("sell_tp_not_below_entry_zone")
            if any(vals[i] < vals[i+1] for i in range(len(vals)-1)): reasons.append("sell_tp_order_non_descending")
        if len(set(vals)) != len(vals): reasons.append("duplicate_tp_price")
        category = "TRADE_SIGNAL" if not reasons else "REJECTED_SIGNAL"
    elif looks_like_signal(text, fields):
        category = "REJECTED_SIGNAL"
        if fields.get("direction") not in {"BUY", "SELL"}: reasons.append("direction_missing_or_ambiguous")
        if fields.get("entry") is None: reasons.append("entry_missing_or_ambiguous")
        if fields.get("stop_loss") is None: reasons.append("stop_loss_missing_or_ambiguous")
        if not fields.get("take_profits"): reasons.append("take_profit_missing_or_ambiguous")
        reasons.append("excluded_from_backtest")
    elif re.search(r"\bmarket\s*alert\b", text, re.I): category = "MARKET_ALERT"
    elif re.search(r"\b(?:move\s+(?:the\s+)?SL|SL\s+to\s+(?:entry|break.?even)|break.?even|cancel(?:led|ed)?\s+(?:the\s+)?signal|position\s+(?:is\s+)?still\s+running|close\s+(?:the\s+)?trade)\b", text, re.I): category = "TRADE_UPDATE"
    elif re.search(r"\b(?:hit\s*TP\s*\d|reached\s*TP\s*\d|TP\s*\d\s*(?:hit|reached|done)|hit\s+(?:SL|stop\s*loss)|\bSL\s+(?:hit|reached)|closed\s+(?:in\s+)?profit|\+\s*\d+\s*pips|secured\s+\+?\d+\s*pips|\d+/\d+\s+TPs?)\b", text, re.I): category = "RESULT_REPORT"
    elif re.search(r"\b(?:join\s+VIP|inside\s+VIP|VIP channel|subscribe|join us|free VIP spots)\b", text, re.I): category = "PROMOTION"
    elif re.search(r"\b(?:support|resistance|market bias|volatility|CPI|NFP|PCE|GDP|news release|market analysis|invalidation area|timeframes reviewed)\b", text, re.I): category = "MARKET_ANALYSIS"
    else: category = "OTHER"
    return category, fields, list(dict.fromkeys(reasons))

def load_messages(path):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, list): messages = data
    elif isinstance(data, dict): messages = data.get("messages", [])
    else: messages = []
    if not isinstance(messages, list): raise ValueError(f"Invalid JSON export structure: {path}")
    return messages

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", nargs="?", default="data/json exports", help="JSON file or directory containing exported JSON files")
    ap.add_argument("--out", default="data/exports/parsed_signals.json")
    ap.add_argument("--csv", default="data/exports/parsed_signals.csv")
    args = ap.parse_args()
    source = Path(args.input)
    if not source.exists(): raise SystemExit(f"Input path not found: {source}")
    sources = sorted(p for p in source.glob("*.json") if p.is_file()) if source.is_dir() else [source]
    if not sources: raise SystemExit(f"No JSON files found in: {source}")
    results, counts, per_source = [], Counter(), {}
    for file_path in sources:
        messages = load_messages(file_path); file_counts = Counter(); file_results = []
        for m in messages:
            category, fields, reasons = classify(m)
            current_text = (m.get("current_text") or m.get("text") or m.get("raw_text") or m.get("message") or "")
            row = {"parser_version": PARSER_VERSION, "source_file": file_path.name,
                "telegram_message_id": m.get("telegram_message_id") or m.get("message_id"),
                "message_date": m.get("message_date") or m.get("date_utc") or m.get("date") or m.get("date_local"),
                "edit_date": m.get("edit_date") or m.get("edit_date_utc"),
                "channel_username": m.get("channel_username"), "channel_title": m.get("channel_title"),
                "category": category, **fields, "validation_flags": reasons,
                "backtest_eligible": category == "TRADE_SIGNAL" and not reasons,
                "extraction_method": "regex", "has_media": bool(m.get("has_media")), "current_text": current_text}
            results.append(row); file_results.append(row); counts[category] += 1; file_counts[category] += 1
        per_source[file_path.name] = {"source_message_count": len(messages), "category_counts": dict(sorted(file_counts.items())),
            "backtest_eligible_signals": sum(r["backtest_eligible"] for r in file_results)}
    output = {"parser_version": PARSER_VERSION, "source_files": [p.name for p in sources],
        "source_message_count": len(results), "category_counts": dict(sorted(counts.items())),
        "backtest_eligible_signals": sum(r["backtest_eligible"] for r in results), "per_source": per_source, "messages": results}
    out, csv_path = Path(args.out), Path(args.csv); out.parent.mkdir(parents=True, exist_ok=True); csv_path.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    fieldnames = ["source_file", "telegram_message_id", "message_date", "edit_date", "channel_username", "channel_title", "category", "symbol", "direction", "entry", "entry_min", "entry_max", "take_profits", "stop_loss", "validation_flags", "backtest_eligible", "extraction_method", "has_media", "current_text"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames); writer.writeheader()
        for r in results:
            row = dict(r); row["take_profits"] = json.dumps(r["take_profits"], ensure_ascii=False); row["validation_flags"] = ";".join(r["validation_flags"])
            writer.writerow({k: row.get(k) for k in fieldnames})
    print(f"Parser version: {PARSER_VERSION}\nInput JSON files: {len(sources)}")
    for name, stats in per_source.items():
        print(f"\n{name}: {stats['source_message_count']} messages")
        for category, count in sorted(stats["category_counts"].items()): print(f"  {category}: {count}")
        print(f"  Backtest-eligible signals: {stats['backtest_eligible_signals']}")
    print(f"\nTotal messages processed: {len(results)}\nTotal category counts:")
    for name, count in sorted(counts.items()): print(f"  {name}: {count}")
    print(f"Backtest-eligible signals: {output['backtest_eligible_signals']}\nJSON output: {out}\nCSV output: {csv_path}")

if __name__ == "__main__": main()
