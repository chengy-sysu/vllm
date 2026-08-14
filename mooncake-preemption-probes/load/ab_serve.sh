#!/bin/bash
# Preemption-forcing server for the pin A/B.
#
# The KV pool is deliberately far smaller than the concurrent working set so the
# allocator, not the store, is the bottleneck: that is the only regime where the
# preempt path (the one this change fixes) actually runs. max_model_len is cut to
# fit the tiny pool, which also drops the yarn override.
cd /home/felixlinker
source /home/felixlinker/.venv/bin/activate
ulimit -l unlimited
export VLLM_HOST_IP=$(ip -o -4 addr show bond0 | awk '{print $4}' | cut -d/ -f1)
export MOONCAKE_CONFIG_PATH=/home/felixlinker/mooncake_config.json

MODEL=/mnt/nvme/shared/felixlinker/models/Qwen3-32B-FP8

exec vllm serve "$MODEL" \
  --served-model-name qwen3-32b \
  --tensor-parallel-size 2 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90 \
  --num-gpu-blocks-override ${BLOCKS:-1024} \
  --enable-prefix-caching \
  ${SERVE_EXTRA:-} \
  --host 0.0.0.0 --port 8000 \
  --kv-transfer-config '{"kv_connector":"MooncakeStoreConnector","kv_role":"kv_both","kv_connector_extra_config":{"load_async":true,"lookup_async":true}}'
