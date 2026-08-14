#!/bin/bash
# One arm of the pin A/B: cold master, preemption-forcing server, short load.
# Usage: TAG=pin JOBID=564 ~/ab_run.sh
set -u
TAG=${TAG:?TAG required}
JOBID=${JOBID:?JOBID required}
BLOCKS=${BLOCKS:-1024}
N=${N:-96}
CONC=${CONC:-48}
WORDS=${WORDS:-400}
MAXTOK=${MAXTOK:-192}
cd /home/felixlinker
source /home/felixlinker/.venv/bin/activate

echo "=== [$TAG] git: $(git -C ~/vllm rev-parse --short HEAD) $(git -C ~/vllm rev-parse --abbrev-ref HEAD)"

TAG=$TAG nohup srun --jobid=$JOBID --overlap -N1 -n1 ~/ab_master.sh \
  > ~/ab_master_$TAG.log 2>&1 &
sleep 10

BLOCKS=$BLOCKS nohup srun --jobid=$JOBID --overlap -N1 -n1 --gres=gpu:2 ~/ab_serve.sh \
  > ~/ab_serve_$TAG.log 2>&1 &

for i in $(seq 1 60); do
  curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1 && break
  sleep 10
done
if ! curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
  echo "=== [$TAG] NEVER HEALTHY"; tail -30 ~/ab_serve_$TAG.log; exit 1
fi
echo "=== [$TAG] healthy at $(date +%T), kv blocks=$(grep -oE 'GPU KV cache size: [0-9,]+' ~/ab_serve_$TAG.log | tail -1)"

metric() { curl -s http://127.0.0.1:8000/metrics | grep -E "^vllm:num_preemptions_total" | awk '{s+=$2} END {print s+0}'; }
PRE_BEFORE=$(metric)

python -u ~/synth_load.py --n $N --concurrency $CONC --words $WORDS \
  --max-tokens $MAXTOK 2>&1 | tail -12

PRE_AFTER=$(metric)
echo "=== [$TAG] preemptions: $PRE_BEFORE -> $PRE_AFTER (delta $((PRE_AFTER - PRE_BEFORE)))"
curl -s http://127.0.0.1:8000/metrics | grep -E "^vllm:(prefix_cache|external_prefix_cache)" | grep -v '#'
