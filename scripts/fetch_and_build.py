#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.utils.database import clean_stocks, sort_stocks
from database.GICS.updater import main as update_gics_hierarchy
from database.updater import run_all_funds_report, run_fetch_nq_filings


def run_static_build() -> None:
    subprocess.run(
        [sys.executable, "scripts/build_institutional_data.py", "--source", "database", "--output", "data/institutional"],
        cwd=ROOT,
        check=True,
    )


def main() -> None:
    os.environ.setdefault("GITHUB_ACTIONS", "true")

    print("::group::Updating GICS hierarchy")
    update_gics_hierarchy()
    print("::endgroup::GICS hierarchy updated")

    print("::group::Fetching full 13F reports")
    run_all_funds_report()
    print("::endgroup::13F reports fetched")

    print("::group::Fetching non-quarterly filings")
    run_fetch_nq_filings()
    print("::endgroup::Non-quarterly filings fetched")

    print("::group::Maintaining stocks database")
    clean_stocks()
    sort_stocks()
    print("::endgroup::Stocks database maintained")

    print("::group::Building institutional static artifacts")
    run_static_build()
    print("::endgroup::Institutional static artifacts built")


if __name__ == "__main__":
    main()
