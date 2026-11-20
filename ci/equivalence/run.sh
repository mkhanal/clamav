#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: run.sh [--runs N] [--report FILE] [--clamcove-ref REF] <sample-directory>..." >&2
  exit 2
}

RUNS=5
REPORT=equivalence-report.md
CLAMCOVE_REF=clamcove-1.5.4.4
DIRECTORIES=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --runs) RUNS="${2:?}"; shift 2 ;;
    --report) REPORT="${2:?}"; shift 2 ;;
    --clamcove-ref) CLAMCOVE_REF="${2:?}"; shift 2 ;;
    -*) usage ;;
    *) DIRECTORIES+=("$(cd "$1" && pwd)"); shift ;;
  esac
done
[ "${#DIRECTORIES[@]}" -gt 0 ] || usage

OFFICIAL_VERSION=1.5.4
OFFICIAL_SHA=1af1117a228f1b5bc7fa91a0dabc37848a99e7d25188e9be8043332ce721dfd3
SIGNATURE_IMAGE='clamav/clamav-debian:1.5.4@sha256:cce3e1a43ae2bb40e11335c52c0e1e98273b12fa3d587e617f63a6907cc4b70b'
REQUIRED_SPEEDUP=3
ALLOWED_SLOWDOWN_PERCENT=15
TIMER_JITTER_MS=10
SPEEDUP_SAMPLES=(report-12-images.docx archive-12-images.zip report-nested.zip)

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(git -C "$HERE" rev-parse --show-toplevel)"
WORK="$(mktemp -d)"
PIDS=()
DATABASE_CONTAINER=
cleanup() {
  for pid in "${PIDS[@]-}"; do
    kill "$pid" > /dev/null 2>&1 || true
  done
  if [ -n "$DATABASE_CONTAINER" ]; then
    docker rm -f "$DATABASE_CONTAINER" > /dev/null 2>&1 || true
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

CMAKE_OPTIONS="-DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_INSTALL_LIBDIR=lib \
  -DAPP_CONFIG_DIRECTORY=/etc/clamav -DDATABASE_DIRECTORY=/var/lib/clamav -DENABLE_CLAMONACC=OFF \
  -DENABLE_EXAMPLES=OFF -DENABLE_JSON_SHARED=ON -DENABLE_MAN_PAGES=OFF -DENABLE_MILTER=OFF \
  -DENABLE_STATIC_LIB=OFF -DENABLE_SYSTEMD=OFF"

echo "== Fetching official ClamAV $OFFICIAL_VERSION"
curl --fail --location --silent --show-error --retry 3 \
  --output "$WORK/clamav.tar.gz" \
  "https://github.com/Cisco-Talos/clamav/releases/download/clamav-$OFFICIAL_VERSION/clamav-$OFFICIAL_VERSION.tar.gz"
echo "$OFFICIAL_SHA  $WORK/clamav.tar.gz" | sha256sum --check
mkdir -p "$WORK/source"
tar -xzf "$WORK/clamav.tar.gz" -C "$WORK/source" --strip-components=1

build_variant() {
  variant="$1"
  source="$2"
  echo "== Building $variant"
  cmake -S "$source" -B "$WORK/build-$variant" $CMAKE_OPTIONS
  cmake --build "$WORK/build-$variant" --parallel
  DESTDIR="$WORK/root-$variant" cmake --install "$WORK/build-$variant" > /dev/null
  echo "== ctest $variant"
  ctest --test-dir "$WORK/build-$variant" --output-on-failure
}

echo "== Checking out ClamCove $CLAMCOVE_REF"
CLAMCOVE_COMMIT="$(git -C "$REPO" rev-parse "$CLAMCOVE_REF^{commit}")"
mkdir -p "$WORK/clamcove-source"
git -C "$REPO" archive "$CLAMCOVE_COMMIT" | tar -x -C "$WORK/clamcove-source"

build_variant official "$WORK/source"
build_variant clamcove "$WORK/clamcove-source"

mkdir -p "$WORK/db"
echo "== Loading databases from $SIGNATURE_IMAGE"
DATABASE_CONTAINER="$(docker create "$SIGNATURE_IMAGE")"
for database in main daily bytecode; do
  docker cp "$DATABASE_CONTAINER:/var/lib/clamav/$database.cvd" "$WORK/db/$database.cvd"
done
docker rm "$DATABASE_CONTAINER" > /dev/null
DATABASE_CONTAINER=
cp "$HERE"/signatures/* "$WORK/db/"

for variant in official clamcove; do
  port=3310
  [ "$variant" = clamcove ] && port=3311
  mkdir -p "$WORK/tmp-$variant"
  cat > "$WORK/clamd-$variant.conf" <<EOF
Foreground yes
TCPSocket $port
TCPAddr 127.0.0.1
DatabaseDirectory $WORK/db
CVDCertsDirectory $WORK/root-$variant/etc/clamav/certs
TemporaryDirectory $WORK/tmp-$variant
DisableCache yes
MaxThreads 2
ReadTimeout 900
CommandReadTimeout 900
StreamMaxLength 4000M
MaxFileSize 4000M
MaxScanSize 4000M
PCREMaxFileSize 4000M
MaxScanTime 900000
AlertExceedsMax yes
EOF
  LD_LIBRARY_PATH="$WORK/root-$variant/usr/lib" \
    "$WORK/root-$variant/usr/sbin/clamd" --config-file="$WORK/clamd-$variant.conf" --foreground \
    > "$WORK/clamd-$variant.log" 2>&1 &
  PIDS+=("$!")
done

for variant in official clamcove; do
  port=3310
  [ "$variant" = clamcove ] && port=3311
  attempt=1
  until printf 'PING\n' | nc -w 2 127.0.0.1 "$port" | grep -q PONG; do
    [ "$attempt" -lt 150 ] || { cat "$WORK/clamd-$variant.log" >&2; exit 1; }
    attempt=$((attempt + 1))
    sleep 2
  done
  printf 'VERSION\n' | nc -w 2 127.0.0.1 "$port" | sed "s/^/== $variant engine: /"
done

scan_file() {
  variant="$1"
  file="$2"
  allmatch="$3"
  port=3310
  [ "$variant" = clamcove ] && port=3311
  options=(--no-summary --config-file="$WORK/clamd-$variant.conf")
  [ "$allmatch" = yes ] && options+=(--allmatch)
  start=$(date +%s%N)
  result=$(LD_LIBRARY_PATH="$WORK/root-$variant/usr/lib" \
    "$WORK/root-$variant/usr/bin/clamdscan" "${options[@]}" "$file" 2>&1 \
    | sed "s|^$file: ||" || true)
  end=$(date +%s%N)
  printf '%s\t%s\n' "$(( (end - start) / 1000000 ))" "$result"
}

: > "$WORK/runs.tsv"
index=0
for directory in "${DIRECTORIES[@]}"; do
  while IFS= read -r file; do
    name="$index/${file#"$directory"/}"
    run=1
    while [ "$run" -le "$RUNS" ]; do
      for variant in official clamcove; do
        printf '%s\t%s\t%s\n' "$variant" "$name" "$(scan_file "$variant" "$file" no)" >> "$WORK/runs.tsv"
      done
      run=$((run + 1))
    done
    for variant in official clamcove; do
      printf '%s\t%s\tallmatch\t%s\n' "$variant" "$name" "$(scan_file "$variant" "$file" yes)" >> "$WORK/runs.tsv"
    done
  done < <(find "$directory" -type f | sort)
  index=$((index + 1))
done

{
  echo '# ClamCove equivalence report'
  echo
  echo "- ClamAV baseline: $OFFICIAL_VERSION (tarball SHA-256 \`$OFFICIAL_SHA\`)"
  echo "- ClamCove source: \`$CLAMCOVE_REF\` (\`$CLAMCOVE_COMMIT\`)"
  echo "- Databases: $(cd "$WORK/db" && ls -1 | paste -sd, -)"
  echo "- Runs per sample: $RUNS, interleaved, plus one \`--allmatch\` scan each"
  echo
} > "$REPORT"

awk -F '\t' -v runs="$RUNS" -v speedup_list="${SPEEDUP_SAMPLES[*]-}" -v required="$REQUIRED_SPEEDUP" \
    -v slowdown="$ALLOWED_SLOWDOWN_PERCENT" -v jitter="$TIMER_JITTER_MS" '
  BEGIN { count = split(speedup_list, listed, " "); for (i = 1; i <= count; i++) gated[listed[i]] = 1 }
  $3 == "allmatch" { every[$1, $2] = $5; next }
  {
    variant = $1; key = $2
    files[key] = 1
    times[variant, key] = times[variant, key] " " $3
    if (!((variant, key) in result)) result[variant, key] = $4
    else if (result[variant, key] != $4) unstable[variant, key] = 1
  }
  function median(list,    values, count, i, j, swap) {
    count = split(substr(list, 2), values, " ")
    for (i = 1; i <= count; i++) for (j = i + 1; j <= count; j++) if (values[j] + 0 < values[i] + 0) { swap = values[i]; values[i] = values[j]; values[j] = swap }
    low = values[1]; high = values[count]
    return values[int((count + 1) / 2)] + 0
  }
  function stats(list,    middle) { middle = median(list); return sprintf("%d (%d-%d)", middle, low, high) }
  END {
    printf "| sample | official ms median (min-max) | ClamCove ms median (min-max) | ratio | result |\n"
    printf "| --- | --- | --- | --- | --- |\n"
    differences = 0; regressions = 0; missing_speedups = 0
    for (key in files) order[++n] = key
    for (i = 1; i <= n; i++) for (j = i + 1; j <= n; j++) if (order[j] < order[i]) { swap = order[i]; order[i] = order[j]; order[j] = swap }
    for (i = 1; i <= n; i++) {
      key = order[i]
      base = key; sub(/^[0-9]+\//, "", base)
      official = median(times["official", key]); clamcove = median(times["clamcove", key])
      ratio = clamcove > 0 ? official / clamcove : 0
      verdict = ""
      same = (result["official", key] == result["clamcove", key]) && (every["official", key] == every["clamcove", key]) && !(("official", key) in unstable) && !(("clamcove", key) in unstable)
      if (!same) { differences++; verdict = verdict "  DIFFERS: official " every["official", key] }
      if (base in gated) {
        if (ratio < required) { missing_speedups++; verdict = verdict "  NOT " required "x FASTER" }
      } else if (clamcove > official * (100 + slowdown) / 100 + jitter) {
        regressions++; verdict = verdict "  SLOWER BY MORE THAN " slowdown "%"
      }
      printf "| %s | %s | %s | %.1fx | %s%s |\n", key, stats(times["official", key]), stats(times["clamcove", key]), ratio, every["clamcove", key], verdict
    }
    printf "\n%d sample(s), %d interleaved run(s) each: %d result difference(s), %d sample(s) not %dx faster, %d sample(s) slower by more than %d%% (+%d ms)\n", n, runs, differences, missing_speedups, required, regressions, slowdown, jitter
    exit (differences + missing_speedups + regressions) > 0
  }' "$WORK/runs.tsv" | tee -a "$REPORT"
