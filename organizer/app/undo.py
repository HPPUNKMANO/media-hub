"""Undo the moves of an organizer run by moving files back where they came from.

Usage (inside the container):
    python -m app.undo --list               # show recent runs
    python -m app.undo                      # preview undo of the latest live run
    python -m app.undo --run 20261111-101500 --apply
"""
from __future__ import annotations

import argparse
import json
import os
from collections import OrderedDict
from pathlib import Path

from .config import from_env
from .fsops import unique_path


def load_runs(journal: Path) -> "OrderedDict[str, list[dict]]":
    runs: OrderedDict[str, list[dict]] = OrderedDict()
    if not journal.exists():
        return runs
    for line in journal.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        runs.setdefault(rec["run_id"], []).append(rec)
    return runs


def undo_run(journal: Path, run_id: str | None = None, apply: bool = False) -> list[str]:
    runs = load_runs(journal)
    runs = OrderedDict((k, v) for k, v in runs.items() if not k.startswith("undo-"))
    if not runs:
        return ["no moves recorded"]
    run_id = run_id or next(reversed(runs))
    if run_id not in runs:
        return [f"run {run_id} not found"]
    out = []
    undo_log = []
    for rec in reversed(runs[run_id]):
        src, dst = Path(rec["src"]), Path(rec["dst"])
        if not dst.exists():
            out.append(f"SKIP (no longer at destination): {dst}")
            continue
        back = unique_path(src)
        out.append(f"{'MOVE' if apply else 'WOULD MOVE'}: {dst} -> {back}")
        if apply:
            back.parent.mkdir(parents=True, exist_ok=True)
            os.rename(dst, back)
            undo_log.append({"run_id": f"undo-{run_id}", "src": str(dst), "dst": str(back), "reason": "undo"})
    if apply and undo_log:
        with journal.open("a", encoding="utf-8") as fh:
            for rec in undo_log:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", help="run id (default: latest)")
    ap.add_argument("--apply", action="store_true", help="actually move files back (default: preview only)")
    ap.add_argument("--list", action="store_true", help="list recorded runs")
    args = ap.parse_args()
    journal = from_env().state_dir / "moves.jsonl"
    if args.list:
        for run_id, recs in load_runs(journal).items():
            print(f"{run_id}: {len(recs)} moves")
        return
    for line in undo_run(journal, args.run, args.apply):
        print(line)


if __name__ == "__main__":
    main()
