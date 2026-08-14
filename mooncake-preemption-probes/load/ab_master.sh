#!/bin/bash
# Mooncake master for one run. TAG picks the root_fs_dir, so changing it is what
# makes the store cold instead of inheriting the previous run's disk replicas.
ulimit -l unlimited
VENV=${VENV:-$HOME/.venv}
source "$VENV/bin/activate"
FSROOT=${FSROOT_BASE:-$HOME/mooncake_fs_ab}_${TAG:?TAG required}
mkdir -p "$FSROOT"
exec mooncake_master \
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
