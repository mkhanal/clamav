#!/bin/sh
# usage: memory-cap-clamd.sh <image> <archive-dir> <archive-name> <memory e.g. 2560m> <concurrent scans>
# Starts clamd in a memory-capped container (no swap), runs N concurrent clamdscan of the same archive,
# and reports verdicts, peak cgroup memory (memory.peak), peak anonymous/file memory (sampled), OOM kills, wall time.
IMG=$1; DIR=$2; NAME=$3; MEM=$4; N=$5
CN=memory-cap-$$
docker run -d --rm --name $CN --memory="$MEM" --memory-swap="$MEM" -v "$DIR":/arch:ro "$IMG" sleep 3600 >/dev/null
docker exec -e NAME="$NAME" -e N="$N" $CN sh -c '
  useradd -r clamav 2>/dev/null; mkdir -p /db /tmp/scan; echo "Test.Marker:0:*:454e444d41524b5f" > /db/marker.ndb; chown -R clamav /db /tmp/scan
  cat > /tmp/clamd.conf <<CONF
LocalSocket /tmp/clamd.sock
DatabaseDirectory /db
TemporaryDirectory /tmp/scan
User clamav
Foreground yes
LogFile /tmp/clamd.log
LogVerbose yes
MaxFileSize 4000M
MaxScanSize 4000M
StreamMaxLength 4000M
MaxScanTime 0
MaxThreads 4
AllowAllMatchScan yes
CONF
  chmod 644 /tmp/clamd.conf; touch /tmp/clamd.log; chown clamav /tmp/clamd.log
  export PATH=/opt/clamav/sbin:$PATH
  clamd -c /tmp/clamd.conf >/tmp/clamd.out 2>&1 &
  CLAMD=$!
  for i in $(seq 1 100); do [ -S /tmp/clamd.sock ] && break; sleep 0.2; done
  ( maxa=0; maxf=0; while :; do
      a=$(awk "/^anon /{print \$2}" /sys/fs/cgroup/memory.stat); f=$(awk "/^file /{print \$2}" /sys/fs/cgroup/memory.stat)
      [ "$a" -gt "$maxa" ] && maxa=$a; [ "$f" -gt "$maxf" ] && maxf=$f; echo "$maxa $maxf" > /tmp/peaks; sleep 0.2
    done ) >/dev/null 2>&1 &
  s=$(date +%s%N)
  PIDS=""
  for i in $(seq 1 $N); do
    ( clamdscan -c /tmp/clamd.conf --allmatch --no-summary /arch/$NAME > /tmp/scan$i.out 2>&1; echo "rc=$?" >> /tmp/scan$i.out ) &
    PIDS="$PIDS $!"
  done
  wait $PIDS
  echo "wall=$(( ($(date +%s%N) - s) / 1000000 ))ms"
  for i in $(seq 1 $N); do echo "scan$i: $(tr "\n" " " < /tmp/scan$i.out | sed "s#/arch/##g; s/UNOFFICIAL //g")"; done
  echo "clamd alive: $([ -d /proc/$CLAMD ] && echo yes || echo NO)   $(grep VmHWM /proc/$CLAMD/status 2>/dev/null)"
  set -- $(cat /tmp/peaks); echo "peak anon(sampled)=$(( $1 / 1048576 )) MiB  peak file(sampled)=$(( $2 / 1048576 )) MiB"
  echo "memory.peak=$(( $(cat /sys/fs/cgroup/memory.peak) / 1048576 )) MiB  $(grep -E "^oom_kill " /sys/fs/cgroup/memory.events)"
'
docker rm -f $CN >/dev/null 2>&1
