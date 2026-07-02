#!/usr/bin/env python3
"""Run the MVP pipeline end-to-end."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(cmd, cwd: Path) -> None:
    print("\n$ " + " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd), check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build collection JSON and portfolio dashboard data")
    parser.add_argument("--excel", help="Path to workbook. Defaults to first .xlsx in repository root")
    parser.add_argument("--sheet", help="Optional worksheet name")
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--offline", action="store_true", help="Do not call Scryfall; use cache/manual matches only")
    parser.add_argument("--use-scryfall-prices", action="store_true", help="Temporary: use Scryfall price fields as current prices")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    py = sys.executable

    cmd = [py, "scripts/excel_to_json.py", "--base-dir", str(base_dir)]
    if args.excel:
        cmd += ["--excel", args.excel]
    if args.sheet:
        cmd += ["--sheet", args.sheet]
    run(cmd, base_dir)

    cmd = [py, "scripts/enrich_scryfall.py", "--base-dir", str(base_dir)]
    if args.offline:
        cmd.append("--offline")
    run(cmd, base_dir)

    cmd = [py, "scripts/build_portfolio_data.py", "--base-dir", str(base_dir)]
    if args.use_scryfall_prices:
        cmd.append("--use-scryfall-prices")
    run(cmd, base_dir)

    print("\nBuild complete. Open public/index.html or publish the public folder with GitHub Pages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
