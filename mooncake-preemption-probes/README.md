# Mooncake store preemption probes

Instrumentation and load scripts used to measure two preemption bugs in
`MooncakeStoreConnector`. **Nothing here is meant for upstream** — the patches
add logging and shadow bookkeeping only, they do not change behaviour.

Two things are measured:

1. **Store jobs read GPU blocks after those blocks have been freed**, so the
   store ends up holding KV that does not belong to the key. Measured by
   content fingerprints (`probes/fingerprint_on_*.patch`).
2. **Request-id reuse across preemption corrupts store-job accounting**
   (vllm-project/vllm#51637). Measured by a shadow ledger and a reference
   ledger (`probes/aba_*.patch`).

## Layout

```
probes/     instrumentation patches, one per arm
analysis/   log parsers
load/       preemption-forcing server + synthetic load
```

## Probes

| Patch | Applies on top of | What it records |
|---|---|---|
| `fingerprint_on_main.patch` | `643c125fa` (unfixed) | KV fingerprints + a scheduler-side block-reallocation detector |
| `fingerprint_on_fix.patch` | `926230bfb` (block-reference fix) | KV fingerprints only — under the fix a referenced block is never reallocated, so the scheduler-side detector is constant zero and was dropped |
| `aba_refprobe_on_unfixed.patch` | `ec33f3d7f` (unfixed worker ledger) | The real `dict[str, int]` ledger is the subject, so a `save_seq` set is kept alongside it purely as the ground truth for staleness, plus the race margin |
| `aba_shadow_ledger_on_fix.patch` | `d82c2e4d6` (the `save_seq`-keyed ledger fix) | Replays the old bare-counter semantics event by event as a shadow ledger that records but never decides, so one run reports both what the old scheme would have got wrong and whether the new one got anything wrong, plus the race margin |

### Fingerprints

A store key names a fixed token range, so the KV under it is fixed too. The
patch takes an 8-byte fingerprint on the GPU just before `batch_put` (the blocks
still hold that key's own KV at that moment) and again on the destination blocks
just after `batch_get`. A disagreement means the bytes the store returned are not
the KV that key names — and because the second fingerprint is measured on the
destination blocks, those bytes are already in the cache a request is about to
attend over.

`PUTLOG` / `GETLOG` lines go to `/tmp/det_<pid>.log`, one file per process. They
must not go through the logger: the lines are long and the two TP ranks
interleave on stdout, which tears them.

The scheduler-side `RACE` lines land in the **server log**, not in
`/tmp/det_*.log`, so both have to be fed to the analyser.

### ABA ledgers and the race margin

A job left over from a retired generation only charges a live generation's
bookkeeping if it reaches the gate *after* its request has resumed and
re-registered under the same id. Both instants happen on their own, so the probes
time them rather than force them: `MARGIN fired` is a job that gated after the
resumption, which is the bug happening, and `MARGIN missed` carries the `miss_ms`
of headroom the job had left. Nothing in the probes delays anything.

That turns a rare boolean into a distribution. In a run with no firings the
number that matters is `min(miss_ms)`: how much slower a PUT would have to be for
the window to close.

To close it without injecting timing, make a PUT legitimately slow instead —
`QUOTA_BYTES` small enough that the master evicts and offloads to disk on the
write path, more concurrency, larger saves. That is a configuration real
deployments run, so the result says something about them rather than about an
injected sleep.

## Running an arm

```bash
salloc -N1 -n1 -c 20 --gres=gpu:2
TAG=base JOBID=<jobid> BLOCKS=1024 N=96 CONC=48 WORDS=400 MAXTOK=192 \
  SERVE_EXTRA=--no-enable-flashinfer-autotune ./load/ab_run.sh
```

`ab_run.sh` starts a cold mooncake master, starts the server, polls `/health`,
and sends the load as soon as it is up. `TAG` picks the master's `root_fs_dir`,
so changing it is what makes the store cold. `BLOCKS` sizes the KV pool; the pool
has to be far smaller than the concurrent working set, because the preempt path
only runs when the allocator, not the store, is the bottleneck.

`synth_load.py` sends random-gibberish prompts so nothing dedups in the store and
every save is a real `batch_put`. At `BLOCKS=1024` with 96 requests / 48
concurrent / 400 words / 192 max tokens it produces 125–288 preemptions per run.

Everything site-specific is an environment variable: `VENV` (default
`$HOME/.venv`), `MODEL` (`Qwen/Qwen3-32B-FP8`), `FSROOT_BASE`
(`$HOME/mooncake_fs_ab`), `MOONCAKE_CONFIG_PATH` (`$HOME/mooncake_config.json`),
`VLLM_REPO` (`$HOME/vllm`, only used to print which commit is under test),
`LOGDIR`, `BASE` (`http://127.0.0.1:8000`), `QUOTA_BYTES` (2 TiB) and `IFACE`,
which is the interface `VLLM_HOST_IP` is taken from and is left unset by
default.

`SERVE_EXTRA=--no-enable-flashinfer-autotune` is required, or
`compile_or_warm_up_model` fails with
`ImportError: cannot import name 'set_autotune_process_group'`.

## Analysis

```bash
python analysis/analyze_evi.py /tmp/det_*.log server.log   # totals
python analysis/bad_dist.py    /tmp/det_*.log server.log   # bad keys per save_seq
python analysis/aba_margin.py  server.log                  # race margin distribution
```

`analyze_evi.py` reports keys fingerprinted, read-backs checked, mismatches,
poisoned keys, requests that read wrong KV, and jobs the scheduler-side detector
flagged. `bad_dist.py` splits the poisoned keys by the store job that wrote them,
which is what shows the two independent signals agreeing.

Both need the server log as well as `/tmp/det_*.log`, otherwise the flagged-job
count reads zero.

`aba_margin.py` reports how many leftover jobs fired, how many missed and by how
little, and echoes the `REF SUMMARY` / `SHADOW SUMMARY` lines. It only reads the
server log.
