#!/bin/sh
# usage: memory-cap-clamscan.sh <image> <archive-dir> <archive-name> <memory e.g. 6g>
# One clamscan in a memory-capped container; prints verdict, cgroup memory.peak, oom_kill, wall time.
IMG=$1; DIR=$2; NAME=$3; MEM=$4
docker run --rm --name memory-cap-$$ --memory="$MEM" --memory-swap="$MEM" -v "$DIR":/arch:ro "$IMG" sh -c '
  mkdir -p /db /tmp/scan && echo "Test.Marker:0:*:454e444d41524b5f" > /db/marker.ndb
  s=$(date +%s%N)
  clamscan -d /db --tempdir=/tmp/scan --allmatch --max-filesize=4000M --max-scansize=4000M --max-scantime=0 /arch/'"$NAME"' 2>&1 | grep -E "FOUND|OK$|ERROR|Data scanned|Time:|Killed" 
  echo "exit=$? wall=$(( ($(date +%s%N) - s) / 1000000 ))ms"
  echo "memory.peak=$(( $(cat /sys/fs/cgroup/memory.peak) / 1048576 )) MiB  $(grep -E "oom_kill " /sys/fs/cgroup/memory.events)"
'
