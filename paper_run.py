"""Run both daily paper records without a console window, logging to data/paper-run.log. Paper only; no orders."""
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

LOG = Path("data/paper-run.log")


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as log:
        sys.stdout = sys.stderr = log
        print(f"--- {datetime.now(timezone.utc).isoformat(timespec='seconds')}", flush=True)
        failed = False
        for name in ("trend_paper", "trend_basket_paper"):
            try:
                __import__(name).run()
            except Exception:
                failed = True
                print(f"{name} failed", flush=True)
                traceback.print_exc()
        sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
