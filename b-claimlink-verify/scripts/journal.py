#!/usr/bin/env python3
"""claimlink journal: append-only search journal. Every lookup the Agent does
lands here, so a reviewer can retrace how each claim was found — and how
candidates were rejected.

  python3 journal.py --work /app/work log --action "grep 缓冲液" \
      --considered 5 --accepted 2 --note "3 条为旧版本，已排除"
  python3 journal.py --work /app/work cat
"""
import argparse
import datetime
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)
    log = sub.add_parser("log")
    log.add_argument("--action", required=True)
    log.add_argument("--considered", type=int)
    log.add_argument("--accepted", type=int)
    log.add_argument("--note")
    sub.add_parser("cat")
    args = ap.parse_args()

    jf = Path(args.work) / "search_journal.jsonl"
    if args.cmd == "log":
        entry = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                 "action": args.action, "considered": args.considered,
                 "accepted": args.accepted, "note": args.note}
        with open(jf, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print("journal: +1 entry")
    else:
        if jf.exists():
            print(jf.read_text(encoding="utf-8"))
        else:
            print("(journal empty)")


if __name__ == "__main__":
    main()
