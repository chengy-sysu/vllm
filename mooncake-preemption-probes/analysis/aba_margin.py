#!/usr/bin/env python3
"""How close the req-id reuse race (vllm-project/vllm#51637) comes to firing.

A store job left over from a retired generation only charges a live generation's
ledger if it reaches the gate after its request has resumed and re-registered.
The probe times both instants without delaying either, so every leftover job
yields one sample:

  fired  the job gated after the resumption  -> the bug is happening now
  missed the job gated before it             -> miss_ms of headroom was left

The interesting number in a run with no firings is min(miss_ms): it is how much
slower a PUT would have to be for the race to close.

Usage: aba_margin.py server.log [more.log ...]
"""

import re
import statistics
import sys

FIRED = re.compile(r"MARGIN fired req=(\S+) seq=(\d+) margin_ms=([\d.]+) queued_ms=([\d.]+)")
MISSED = re.compile(r"MARGIN missed req=(\S+) seq=(\d+) miss_ms=([\d.]+)")
SUMMARY = re.compile(r"(REF|SHADOW) SUMMARY .*")


def main(paths: list[str]) -> None:
    fired: list[tuple[str, int, float, float]] = []
    missed: list[tuple[str, int, float]] = []
    summaries: list[str] = []
    for path in paths:
        with open(path, errors="replace") as fh:
            for line in fh:
                if m := FIRED.search(line):
                    fired.append((m[1], int(m[2]), float(m[3]), float(m[4])))
                elif m := MISSED.search(line):
                    missed.append((m[1], int(m[2]), float(m[3])))
                elif m := SUMMARY.search(line):
                    summaries.append(m[0].strip())

    print(f"leftover jobs timed            : {len(fired) + len(missed)}")
    print(f"  fired (bug window closed)    : {len(fired)}")
    print(f"  missed (headroom left)       : {len(missed)}")
    if fired:
        margins = sorted(f[2] for f in fired)
        print(f"  margin_ms min/med/max        : "
              f"{margins[0]:.1f} / {statistics.median(margins):.1f} / {margins[-1]:.1f}")
        for req, seq, margin, queued in fired[:10]:
            print(f"    req={req} seq={seq} margin_ms={margin:.1f} queued_ms={queued:.1f}")
    if missed:
        miss = sorted(m[2] for m in missed)
        pct = [miss[int(len(miss) * q)] for q in (0.0, 0.01, 0.05, 0.5)]
        print(f"  miss_ms min/p1/p5/p50        : "
              f"{pct[0]:.1f} / {pct[1]:.1f} / {pct[2]:.1f} / {pct[3]:.1f}")
        print("  closest misses               :")
        for req, seq, ms in sorted(missed, key=lambda x: x[2])[:10]:
            print(f"    req={req} seq={seq} miss_ms={ms:.1f}")
    for line in summaries:
        print(line)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
