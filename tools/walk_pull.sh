#!/bin/zsh
# Bring a walk back off the phone: the recording, the descriptions, both.
#
# The two files share a stem and have to stay paired — walk_card.py draws each answer over
# the frames it was computed from, and a .jsonl matched to the wrong .mov produces a video
# that looks right and says the wrong thing about every shot.
#
# usage: tools/walk_pull.sh            # newest walk
#        tools/walk_pull.sh walk-1755600000
set -u
UDID=${WCAS_UDID:-A6F3E849-1947-5202-9AD1-9C881CA58EEF}
BUNDLE=com.whatcanaisee.walk
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 1
if [[ -d /Applications/Xcode-27.0.0-Beta.5.app ]]; then
  export DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.5.app/Contents/Developer
else
  export DEVELOPER_DIR=$(xcode-select -p)
fi
mkdir -p runs/walk
STEM=${1:-}
if [[ -z "$STEM" ]]; then
  echo "listing walks on the device …"
  xcrun devicectl device info files --device "$UDID" --domain-type appDataContainer \
    --domain-identifier "$BUNDLE" --username mobile 2>/dev/null | grep -o 'walk-[0-9]*' | sort -u
  echo
  echo "re-run with one of the stems above"
  exit 0
fi
for ext in mov jsonl; do
  xcrun devicectl device copy from --device "$UDID" --domain-type appDataContainer \
    --domain-identifier "$BUNDLE" --source "Documents/${STEM}.${ext}" \
    --destination "runs/walk/${STEM}.${ext}" && echo "  runs/walk/${STEM}.${ext}"
done
echo
echo "next: python3 tools/walk_card.py --walk runs/walk/${STEM}"
