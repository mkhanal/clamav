#!/bin/sh
# Generates fixtures/generated/*.rar with RARLAB rar 6.24 (the last release that can
# write RAR4; it also writes RAR5). rar is a throwaway tool: fetched, run in a
# container, never committed or shipped.
#
#   curl -O https://www.rarlab.com/rar/rarlinux-x64-624.tar.gz
#   # sha256 88e22a8e84125c947637bbf28c746e338a0a63279d80f9f9d7373603875db1eb
#   tar xzf rarlinux-x64-624.tar.gz
#   python3 -I payloads.py /tmp/rp-payloads
#   docker run --rm --platform linux/amd64 -v "$PWD/rar:/r:ro" -v /tmp/rp-payloads:/pay:ro \
#       -v "$PWD/fixtures/generated:/out" -v "$PWD/make-fixtures.sh:/make.sh:ro" \
#       debian:trixie-slim sh /make.sh
set -eu
export LANG=C.UTF-8 LC_ALL=C.UTF-8
RAR=/r/rar
O=/out
W=$(mktemp -d)
cd "$W"
cp -r /pay/. .
mkdir -p tree/sub/deeper tree/emptydir uni
cp marker.txt tree/top.txt
cp marker2.txt tree/sub/inner.txt
cp text.txt tree/sub/deeper/deep.txt
cp marker.txt "uni/ünï-名前-😀.txt"
printf 'Comment text for the archive RARPARITY-COMMENT\n' > comment.txt
rm -f "$O"/*.rar

mk() { name=$1; shift; "$RAR" a -idq -y -ep1 "$O/$name" "$@" >/dev/null 2>&1 || { echo "FAILED $name" >&2; exit 1; }; }
mkr() { name=$1; shift; "$RAR" a -idq -y -r "$O/$name" "$@" >/dev/null 2>&1 || { echo "FAILED $name" >&2; exit 1; }; }

for v in 4 5; do
  a="-ma$v"
  mk gen-rar$v-stored.rar         $a -m0 marker.txt text.txt
  mk gen-rar$v-compressed.rar     $a -m3 marker.txt text.txt
  mk gen-rar$v-best.rar           $a -m5 marker.txt text.txt
  mk gen-rar$v-solid.rar          $a -s -m3 marker.txt marker2.txt text.txt
  mk gen-rar$v-solid-stored.rar   $a -s -m0 marker.txt marker2.txt
  mk gen-rar$v-comment.rar        $a -zcomment.txt marker.txt
  mk gen-rar$v-large-dict.rar     $a -m5 -md$( [ $v = 4 ] && echo 4096k || echo 256m ) text.txt zeros.bin
  mkr gen-rar$v-directories.rar   $a tree
  mkr gen-rar$v-unicode-names.rar $a uni
  mk gen-rar$v-filter-x86.rar     $a -m5 -mcE+ x86.bin
  mk gen-rar$v-filter-delta.rar   $a -m5 -mc2D+ delta.bin
  mk gen-rar$v-encrypted-data.rar    $a -pSecret1 marker.txt text.txt
  mk gen-rar$v-encrypted-headers.rar $a -hpSecret1 marker.txt text.txt
  mk gen-rar$v-encrypted-solid.rar   $a -s -pSecret1 marker.txt marker2.txt
  mk gen-rar$v-encrypted-partial.rar $a marker.txt
  "$RAR" a -idq -y -ep1 $a -pSecret1 "$O/gen-rar$v-encrypted-partial.rar" marker2.txt >/dev/null
  mk gen-rar$v-multivolume.rar $a -v8k -m3 text.txt x86.bin marker.txt
done
mk gen-rar4-filter-audio.rar    -ma4 -m5 -mc2A+ audio.wav
mk gen-rar4-filter-rgb.rar      -ma4 -m5 -mc3C+ rgb.bmp
mk gen-rar4-filter-itanium.rar  -ma4 -m5 ia64.bin
mk gen-rar4-ppmd.rar            -ma4 -m5 -mct+ text.txt marker.txt

for fmt in 4 5; do
  a="-ma$fmt"
  mk nest-rar$fmt-depth1.rar $a marker.txt
  prev=nest-rar$fmt-depth1.rar
  for d in 2 3 4 5 6; do
    cp "$O/$prev" "inner-d$((d-1)).rar"
    mk nest-rar$fmt-depth$d.rar $a "inner-d$((d-1)).rar"
    prev=nest-rar$fmt-depth$d.rar
  done
done
for v in 4 5; do
  mk bomb-rar$v-high-ratio.rar -ma$v -m5 zeros4m.bin
  mkr bomb-rar$v-many-files.rar -ma$v -m3 many
done
ls "$O"
