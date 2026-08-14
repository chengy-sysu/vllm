#!/bin/bash
# Mooncake master for the pin A/B. Each run gets its own root_fs_dir so both
# arms start from a cold store instead of inheriting the previous arm's disk
# replicas.
ulimit -l unlimited
FSROOT=/mnt/nvme/shared/felixlinker/mooncake_fs_ab_${TAG:?TAG required}
mkdir -p "$FSROOT"
exec /home/felixlinker/.venv/bin/mooncake_master \
  --rpc_port=50051 \
  --metrics_port=19004 \
  --enable_http_metadata_server=true \
  --http_metadata_server_port=18080 \
  --enable_offload=true \
  --root_fs_dir="$FSROOT" \
  --enable_disk_eviction=true \
  --offload_on_evict=false \
  --promotion_on_hit=false \
  --offload_force_evict=true \
  --offloading_queue_limit=500000 \
  --offload_cap_ratio=1.0 \
  --quota_bytes=2199023255552 \
  --eviction_high_watermark_ratio=0.90 \
  --enable_metric_reporting=false
