"""Break the fingerprint mismatches down by the store job that wrote them."""

import re
import sys
from collections import Counter, defaultdict

race_re = re.compile(r"RACE seq=(\d+) tow=([\d.]+)")
put_re = re.compile(r"PUTLOG seq=(\S+) t0=([\d.]+) t1=([\d.]+) n=(\d+) nfail=(\d+) k=(\S*)")
get_re = re.compile(r"GETLOG req=(\S+) t=([\d.]+) n=(\d+) k=(\S*)")


def parse_kd(blob):
    out = []
    for item in blob.split(","):
        if not item:
            continue
        k, _, d = item.rpartition(":")
        if k:
            out.append((k, int(d)))
    return out


flagged = set()
put_dg = defaultdict(set)
put_seq = defaultdict(set)
put_t = {}
gets = []
for p in sys.argv[1:]:
    for line in open(p, errors="replace"):
        if m := race_re.search(line):
            flagged.add(int(m.group(1)))
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
bad_keys = set()
bad_reqs = set()
for t, req, items in gets:
    for k, d in items:
        if k not in put_dg or k in ambiguous or t < put_t[k]:
            continue
        if d not in put_dg[k]:
            bad_keys.add(k)
            bad_reqs.add(req)

per_seq = Counter()
for k in bad_keys:
    for s in put_seq.get(k, ("?",)):
        per_seq[s] += 1

print(f"flagged save_seqs (scheduler)  : {len(flagged)} -> {sorted(flagged)}")
print(f"distinct corrupted keys        : {len(bad_keys)}")
print(f"requests that read wrong KV    : {len(bad_reqs)}")
print(f"corrupted keys per save_seq    :")
for s, n in per_seq.most_common():
    mark = " <-- flagged by scheduler" if s in flagged else ""
    print(f"  save_seq={s}: {n} keys{mark}")
