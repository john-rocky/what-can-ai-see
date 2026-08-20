#!/bin/bash
# Run a task file through several models, one at a time, and refuse to do it if
# another run is already alive.
#
# Two loops once wrote to the same .jsonl at the same time. The output looked
# complete — 95 lines for 89 tasks — and the corruption only showed up as two
# JSON objects concatenated on one line, hundreds of lines in. Nothing upstream
# noticed: every id was present, every answer parsed, the tally was simply wrong.
# The cause was `nohup … &` inside an already-backgrounded call, which returned
# "completed" for the wrapper while the child kept running.
#
# So: one runner at a time, machine-wide, and the target file is removed rather
# than appended to. A partial file re-run from scratch costs minutes; a silently
# doubled one costs a retraction.
#
# usage:
#   tools/run_models.sh <tasks.jsonl> <out-dir> [model …]

set -u
tasks="${1:?tasks file}"; out="${2:?out dir}"; shift 2
models=("$@"); [ ${#models[@]} -eq 0 ] && models=(lfm2.5-vl-3b qwen3-vl-2b minicpm-v-4.6)

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root" || exit 1

if pgrep -f 'wcas-run --model' > /dev/null; then
  echo "refusing to start: a wcas-run is already alive" >&2
  ps -eo pid,etime,command | grep 'wcas-run --model' | grep -v grep >&2
  exit 3
fi

mkdir -p "$out"
for m in "${models[@]}"; do
  rm -f "$out/$m.jsonl"
  runner/.build/release/wcas-run --model "$m" --tasks "$tasks" --out "$out/$m.jsonl" \
    >> "$out/run.log" 2>&1
  n=$(wc -l < "$out/$m.jsonl" 2>/dev/null | tr -d ' ')
  u=$(python3 -c "
import json,sys
ids=set()
for l in open('$out/$m.jsonl'):
    l=l.strip()
    if not l: continue
    try: ids.add(json.loads(l)['id'])
    except Exception: print('CORRUPT', file=sys.stderr)
print(len(ids))" 2>/dev/null)
  t=$(wc -l < "$tasks" | tr -d ' ')
  # Empty answers are the failure mode that looks like success: one line per task,
  # every id present, every field parsing, and nothing said. See F24.
  e=$(python3 -c "
import json
n=0
for l in open('$out/$m.jsonl'):
    l=l.strip()
    if not l: continue
    try: d=json.loads(l)
    except Exception: continue
    if not d.get('ok') or len((d.get('answer') or '').strip()) < 4: n+=1
print(n)" 2>/dev/null)
  echo "DONE $m  $(date +%H:%M:%S)  lines=$n unique=$u tasks=$t empty=$e" >> "$out/run.log"
  [ "${e:-0}" -gt 0 ] && echo "  WARNING: $m returned $e empty answer(s) of $t" >&2
done
echo ALLDONE >> "$out/run.log"
