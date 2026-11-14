#!/bin/sh
set -e
R6=/ext/rarlinux-x64-624/rar/rar
R7=/ext/rarlinux-x64-720/rar/rar
O=/fix2/out
W=/tmp/w; rm -rf $W; mkdir -p $W/d $W/v; cd $W
M='ClamAV-RAR-backend-test-marker-6f1c2e'
python3 - "$M" <<'PY'
import random, sys
m = sys.argv[1]
random.seed(11)
words = ['alpha ','beta ','gamma ','delta ','omega ','\n']
txt = ''.join(random.choice(words) for _ in range(3000))
open('d/1-text.txt','w').write(txt)
open('d/2-marker.txt','w').write('before ' + m + ' after\n')
open('big.txt','w').write(('x' * 1000 + '\n') * 2100)   # ~2 MB, highly compressible
open('marker.txt','w').write(m + '\n')
open('v/span.bin','wb').write(bytes(random.getrandbits(8) for _ in range(6000)) + m.encode() + bytes(random.getrandbits(8) for _ in range(6000)))
PY
printf '%s comment\n' "$M" > cmt.txt
$R6 a -idq -ma4 -s -m5 -mcT+ $O/rar4-solid-ppmd.rar d/1-text.txt d/2-marker.txt
$R6 a -idq -ma4 -s -m3 $O/rar4-solid-skip.rar big.txt marker.txt
$R6 a -idq -ma4 -m3 -zcmt.txt $O/rar4-comment.rar d/1-text.txt
$R7 a -idq -ma5 -m3 -zcmt.txt $O/rar5-comment.rar d/1-text.txt
$R6 a -idq -ma4 -m3 -ppw $O/rar4-encrypted-data.rar d/2-marker.txt
$R6 a -idq -ma4 -m3 -hppw $O/rar4-encrypted-headers.rar d/2-marker.txt
$R7 a -idq -ma5 -m3 -ppw $O/rar5-encrypted-data.rar d/2-marker.txt
$R7 a -idq -ma5 -m3 -hppw $O/rar5-encrypted-headers.rar d/2-marker.txt
$R6 a -idq -ma4 -m3 -v8k $O/rar4-volume.rar v/span.bin marker.txt
$R7 a -idq -ma5 -m3 -v8k $O/rar5-volume.rar v/span.bin marker.txt
$R7 a -idq -ma5 -s -m3 $O/rar5-solid-skip.rar big.txt marker.txt
ls -la $O
