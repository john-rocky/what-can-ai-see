#!/bin/zsh
# Run the device bench and bring its numbers back.
#
# The app never exits on its own (a SwiftUI app has nowhere to exit to), so this launches it
# with the console attached, polls the log for the STATS line, and kills the local devicectl
# once it lands. That pattern is inherited from ondevice/_pipelined_device_probe.sh, where it
# was learned the hard way: killing on a timer instead of on a marker cut runs off mid-load
# and produced logs that looked like crashes.
#
# The cap is generous on purpose. The first launch for a model downloads the bundle over the
# network and then specializes it for this GPU — minutes, legitimately — and a run killed
# during that looks exactly like a hang.
#
# usage:
#   tools/phone_run.sh lfm2.5-vl-450m
#   tools/phone_run.sh lfm2.5-vl-3b 20            # cap at 20 windows
#   WCAS_MAX_TOKENS=48 tools/phone_run.sh qwen3-vl-2b

set -u
MODEL=${1:?usage: phone_run.sh <catalog-id> [n-windows]}
N=${2:-}
UDID=${WCAS_UDID:-A6F3E849-1947-5202-9AD1-9C881CA58EEF}   # DaisukeのiPhone (iPhone 17 Pro)
BUNDLE=com.whatcanaisee.phonebench
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 1

if [[ -d /Applications/Xcode-27.0.0-Beta.5.app ]]; then
  export DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.5.app/Contents/Developer
else
  export DEVELOPER_DIR=$(xcode-select -p)
fi

mkdir -p runs/phone
LOG="runs/phone/${MODEL}.log"
: > "$LOG"

ENV_JSON="{\"WCAS_MODEL\":\"${MODEL}\""
[[ -n "$N" ]] && ENV_JSON="${ENV_JSON},\"WCAS_N\":\"${N}\""
[[ -n "${WCAS_MAX_TOKENS:-}" ]] && ENV_JSON="${ENV_JSON},\"WCAS_MAX_TOKENS\":\"${WCAS_MAX_TOKENS}\""
# WCAS_GREEDY=1 tools/phone_run.sh system  — argmax instead of sampling.
[[ -n "${WCAS_GREEDY:-}" ]] && ENV_JSON="${ENV_JSON},\"WCAS_GREEDY\":\"${WCAS_GREEDY}\""
ENV_JSON="${ENV_JSON}}"

echo "launching $MODEL on $UDID …"
xcrun devicectl device process launch --device "$UDID" --console --terminate-existing \
  --environment-variables "$ENV_JSON" "$BUNDLE" > "$LOG" 2>&1 &
CPID=$!

# 60 minutes. A 3B on a phone at ~15 s/window plus a cold download is genuinely this slow;
# the marker, not the clock, decides when to stop.
for i in {1..1800}; do
  grep -qE "^\[.*\] (STATS|ERROR)" "$LOG" && sleep 3 && break
  sleep 2
done
kill $CPID 2>/dev/null

echo
grep -E "device:|physical memory|loaded in|STATS|ERROR|RESULTS" "$LOG"
echo

# Pull the per-window results off the phone. Without this only the summary survives, and the
# answers are half the point: if the phone's text differs from the Mac's, every finding in
# this repo is a Mac finding.
OUT="runs/phone/${MODEL}.jsonl"
if xcrun devicectl device copy from --device "$UDID" --domain-type appDataContainer \
     --domain-identifier "$BUNDLE" --source "Documents/${MODEL}.jsonl" \
     --destination "$OUT" > /dev/null 2>&1; then
  echo "results: $OUT ($(wc -l < "$OUT" | tr -d ' ') lines)"
else
  echo "results: could not copy Documents/${MODEL}.jsonl — check the log"
fi
echo "log:     $LOG"
