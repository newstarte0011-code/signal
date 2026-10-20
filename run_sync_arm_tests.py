"""
Reusable test runner for Signal Analyzer.

Copy this file to tests/run_sync_arm_tests.py.

Run offline tests:
    python tests/run_sync_arm_tests.py

Run offline + real Telegram tests:
    python tests/run_sync_arm_tests.py --live

Run only live Telegram tests:
    python tests/run_sync_arm_tests.py --only live
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# Offline tests: use temporary databases or local configuration where possible.
OFFLINE_TESTS = [
    "tests/test_database_connection.py",
    "tests/test_database_schema.py",
    "tests/test_database_repository.py",
    "tests/test_repository_batch.py",
    "tests/test_logging_setup.py",
    "tests/test_message_versions_repeat.py",
    "tests/test_message_version_lifecycle.py",
    "tests/test_reply_metadata.py",
    "tests/test_telegram_settings.py",
]

# These use the real Telegram session/network and are opt-in.
LIVE_TESTS = [
    "tests/test_telegram_sync.py",
    "tests/test_telegram_history.py",
    "tests/test_telegram_history_verify.py",
]


def run_test(relative_path: str, env: dict[str, str]) -> int:
    print("\n" + "=" * 78, flush=True)
    print(f"TEST: {relative_path}", flush=True)
    print("-" * 78, flush=True)
    result = subprocess.run(
        [sys.executable, "-u", str(PROJECT_ROOT / relative_path)],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
    )
    print("-" * 78, flush=True)
    print(
        f"RESULT: {'PASS' if result.returncode == 0 else 'FAIL'} "
        f"(exit code {result.returncode})",
        flush=True,
    )
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Signal Analyzer tests.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Include tests that connect to the real Telegram account/session.",
    )
    parser.add_argument(
        "--only",
        choices=("all", "offline", "live"),
        default="all",
        help="Choose test group. Default runs offline tests only.",
    )
    args = parser.parse_args()

    run_offline = args.only in ("all", "offline")
    run_live = args.live or args.only == "live"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")

    selected: list[str] = []
    if run_offline:
        selected.extend(OFFLINE_TESTS)
    if run_live:
        selected.extend(LIVE_TESTS)

    print("Signal Analyzer test runner", flush=True)
    print(f"Project root: {PROJECT_ROOT}", flush=True)
    print(f"Python: {sys.executable}", flush=True)
    print(f"Live Telegram tests enabled: {run_live}", flush=True)

    results: list[tuple[str, int | None]] = []
    for relative_path in selected:
        if not (PROJECT_ROOT / relative_path).is_file():
            print(f"\nSKIP: test file not found: {relative_path}", flush=True)
            results.append((relative_path, None))
            continue
        try:
            code = run_test(relative_path, env)
        except KeyboardInterrupt:
            print("\nTest run interrupted by user.", flush=True)
            return 130
        results.append((relative_path, code))

    print("\n" + "=" * 78, flush=True)
    print("FINAL SUMMARY", flush=True)
    print("=" * 78, flush=True)
    for name, code in results:
        status = "SKIP" if code is None else ("PASS" if code == 0 else "FAIL")
        print(f"{status:5} | {name}", flush=True)

    passed = sum(code == 0 for _, code in results)
    failed = sum(code not in (0, None) for _, code in results)
    skipped = sum(code is None for _, code in results)
    print(f"\nPassed: {passed} | Failed: {failed} | Skipped: {skipped}", flush=True)
    if not run_live:
        print("Live Telegram tests were not run. Add --live to include them.", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
    
