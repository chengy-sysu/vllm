"""Compare the KV fingerprint taken before each store PUT against the one taken
after the matching GET.

The store key names a fixed token range, so the KV under it is fixed too. A
fingerprint recorded on the GPU just before the transfer and one recorded on the
GPU just after the value is read back can only disagree if the bytes the store
holds are not the KV that key names -- and since the disagreeing fingerprint is
measured on the destination blocks, those bytes are already in the cache the
request is about to attend over.
"""

import re
import sys
from collections import defaultdict

paths = sys.argv[1:]

race_re = re.compile(r"RACE seq=(\d+) tow=([\d.]+) blocks=(\d+) ranks_busy=(\d+)/(\d+)")
put_re = re.compile(r"PUTLOG seq=(\S+) t0=([\d.]+) t1=([\d.]+) n=(\d+) nfail=(\d+) k=(\S*)")
get_re = re.compile(r"GETLOG req=(\S+) t=([\d.]+) n=(\d+) k=(\S*)")


def parse_kd(blob: str) -> list[tuple[str, int]]:
    out = []
    for item in blob.split(","):
        if not item:
            continue
        k, _, d = item.rpartition(":")
        if k:
            out.append((k, int(d)))
    return out


overwrite: dict[int, float] = {}
put_seq: dict[str, set[int]] = defaultdict(set)  # key -> save_seqs that wrote it
put_dg: dict[str, set[int]] = defaultdict(set)  # key -> fingerprints before put
put_t: dict[str, float] = {}
gets: list[tuple[float, str, list[tuple[str, int]]]] = []

lines = (line for p in paths for line in open(p, errors="replace"))
if True:
    for line in lines:
        if m := race_re.search(line):
            seq, tow = int(m.group(1)), float(m.group(2))
            overwrite[seq] = min(overwrite.get(seq, tow), tow)
        elif m := put_re.search(line):
            seq_s, t1 = m.group(1), float(m.group(3))
            for k, d in parse_kd(m.group(6)):
                put_dg[k].add(d)
                put_t[k] = min(put_t.get(k, t1), t1)
                if seq_s != "None":
                    put_seq[k].add(int(seq_s))
        elif m := get_re.search(line):
            gets.append((float(m.group(2)), m.group(1), parse_kd(m.group(4))))

gets.sort()

ambiguous = {k for k, ds in put_dg.items() if len(ds) > 1}
checked = matched = 0
bad: list[tuple[str, str, int, int]] = []
for t, req, items in gets:
    for k, d in items:
        if k not in put_dg or k in ambiguous or t < put_t[k]:
            continue
        checked += 1
        if d in put_dg[k]:
            matched += 1
        else:
            bad.append((req, k, next(iter(put_dg[k])), d))

print(f"overwritten jobs flagged by scheduler : {len(overwrite)}")
print(f"keys written with a fingerprint       : {len(put_dg)}")
print(f"  excluded (written twice, differing) : {len(ambiguous)}")
print(f"read-backs checked                    : {checked}")
print(f"  fingerprint matched                 : {matched}")
print(f"  MISMATCH (wrong KV loaded and used) : {len(bad)}")

bad_keys = {b[1] for b in bad}
bad_seqs = {s for b in bad for s in put_seq.get(b[1], ())}
print(f"distinct corrupted keys               : {len(bad_keys)}")
print(f"  written by a flagged save_seq       : {len(bad_seqs & overwrite.keys())}")
for req, k, want, got in bad[:10]:
    seqs = sorted(put_seq.get(k, ()))
    print(f"  req={req} key={k} expected={want} got={got} put_by_save_seq={seqs}")
