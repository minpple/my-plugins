#!/usr/bin/env bash
# Judge check (architecture 4.13 "judge checks"): run my-agent:verifier on each fixture and compare the verify.md it
# writes with expected.json (notes) or expected-checks.json (folder fixtures). Paid (one verifier run per fixture,
# capped by --max-budget-usd); run it by hand after changing verifier.md or reviewer.md. Each fixture gets its own
# throwaway git project with a <task_dir>/.active (${MA_TASK_DIR:-.my-agent}), so scope-guard applies exactly as in a
# real task.
# - A note runs as a research task: its first verify.md line must match expected.json.
# - A folder fixture (checks-*) runs as a dev task on its project (key `project`, default checks-project): base/
#   committed, change/ (the fixture's own folder when it has one, else the project's) copied over it uncommitted,
#   task/* plus the case's checks.md, checks/ and changed-files.md in the task folder. It passes when the verdict
#   matches, the criterion's line starts `- <n>. <line>` (key `line`, default FAIL), and the `## Commands run` section
#   agrees: with `ran`, a line holds that text without `(checks.md)` (the verifier ran the suite itself); with
#   `reused`, a line holds that exact command with `(checks.md` and none holds it without (the verifier reused the
#   record). Key `previous` names a file of the fixture folder that becomes the previous verify.md (an archived run 1).
#   Only these runs get Bash.
# usage: run-judge-check.sh [--out FILE] [name ...]   (default: every entry of expected.json and expected-checks.json)
#   --out FILE appends a header line and the printed result lines to FILE (created when missing).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PLUGIN="$(cd "$HERE/../.." && pwd)"
TASK=261025-judge
TD="${MA_TASK_DIR:-.my-agent}"
OUT=""
if [ "${1:-}" = "--out" ]; then
  [ -n "${2:-}" ] || { echo "usage: run-judge-check.sh [--out FILE] [name ...]" >&2; exit 2; }
  OUT="$2"
  shift 2
fi
NOTE_TOOLS="Agent Read Grep Glob Write WebFetch"
FOLDER_TOOLS="$NOTE_TOOLS Bash"
NAMES=("$@")
[ ${#NAMES[@]} -gt 0 ] || read -r -a NAMES <<< "$(python3 -c 'import json,sys; print(" ".join(k for f in sys.argv[1:] for k in json.load(open(f))))' "$HERE/expected.json" "$HERE/expected-checks.json")"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/judge-XXXXXX")"

say() {   # print a result line, and append it to --out FILE
  echo "$1"
  [ -z "$OUT" ] || printf '%s\n' "$1" >> "$OUT"
}

if [ -n "$OUT" ]; then
  printf 'judge-check %s plugin %s names: %s\n' "$(date '+%Y-%m-%d %H:%M')" \
    "$(git -C "$PLUGIN" rev-parse --short HEAD 2>/dev/null || echo none)" "${NAMES[*]}" >> "$OUT"
fi

field() {   # field <json file> <name> [key]: the entry, or one key of it
  python3 -c 'import json,sys; v=json.load(open(sys.argv[1]))[sys.argv[2]]; print(v[sys.argv[3]] if len(sys.argv) > 3 else v)' "$@"
}

opt() {   # opt <json file> <name> <key> <default>: one key of the entry, or the default when it has none
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]].get(sys.argv[3], sys.argv[4]))' "$@"
}

is_folder() {
  python3 -c 'import json,sys; sys.exit(0 if sys.argv[2] in json.load(open(sys.argv[1])) else 1)' "$HERE/expected-checks.json" "$1"
}

run_note() {
  local note=$1 want proj T prompt got
  want=$(field "$HERE/expected.json" "$note")
  proj="$WORK/${note%.md}"
  T="$proj/$TD/$TASK"
  mkdir -p "$T/work"
  git init -q "$proj"
  printf 'task: %s\nphase: 4\nsession: judge\nstarted: 2026-10-25 00:00\n' "$TASK" > "$proj/$TD/.active"
  printf 'Status: active\nProfile: research\nTask: %s\nRequest: shlex summary note\n' "$TASK" > "$T/intake.md"
  cp "$HERE/scope.md" "$T/scope.md"
  printf '# Plan\n\n## Approval\n\n- Approved 2026-10-25 09:30 G1-B\n' > "$T/plan.md"   # Verify runs after G1-B
  cp "$HERE/$note" "$T/work/final.md"
  prompt="Call the agent my-agent:verifier exactly once with exactly this prompt, wait for it, then print the first line of $T/verify.md and stop. This is a judge test: do not invoke any skill (no /my-agent continue).

Completion criteria file: $T/scope.md
Scope change: none
Deliverable: $T/work/final.md
intake: $T/intake.md
Result path: $T/verify.md"
  (cd "$proj" && printf '%s\n' "$prompt" | claude -p --plugin-dir "$PLUGIN" --model haiku --max-budget-usd 2 \
      --permission-mode acceptEdits --allowedTools $NOTE_TOOLS \
      > "$proj/run.out" 2> "$proj/run.err")
  got=$(head -1 "$T/verify.md" 2>/dev/null | sed 's/^Verdict: //; s/^ALL //')
  if [ "$got" = "$want" ]; then
    say "ok   $note: $want"
  else
    say "MISS $note: want $want, got '${got:-no verify.md}' (see $proj)"
    fail=1
  fi
}

run_folder() {
  local name=$1 want crit ran proj T prompt got line ranline miss="" project wantline reused previous prevline="" what
  want=$(field "$HERE/expected-checks.json" "$name" verdict)
  crit=$(field "$HERE/expected-checks.json" "$name" criterion)
  project=$(opt "$HERE/expected-checks.json" "$name" project checks-project)
  wantline=$(opt "$HERE/expected-checks.json" "$name" line FAIL)
  reused=$(opt "$HERE/expected-checks.json" "$name" reused "")
  previous=$(opt "$HERE/expected-checks.json" "$name" previous "")
  ran=$(opt "$HERE/expected-checks.json" "$name" ran "")
  proj="$WORK/$name"
  T="$proj/$TD/$TASK"
  mkdir -p "$proj"
  git init -q "$proj"
  printf '%s/\n__pycache__/\nrun.out\nrun.err\n' "$TD" >> "$proj/.git/info/exclude"
  cp -R "$HERE/$project/base/." "$proj/"
  git -C "$proj" add -A
  git -C "$proj" -c user.name=judge -c user.email=judge@example.invalid -c commit.gpgsign=false commit -qm base
  if [ -d "$HERE/$name/change" ]; then   # the change stays an uncommitted diff
    cp -R "$HERE/$name/change/." "$proj/"
  else
    cp -R "$HERE/$project/change/." "$proj/"
  fi
  mkdir -p "$T/work"
  printf 'task: %s\nphase: 4\nsession: judge\nstarted: 2026-10-25 00:00\n' "$TASK" > "$proj/$TD/.active"
  printf 'Status: active\nProfile: dev\nTask: %s\nLocation: %s\nRequest: calc mul\n' "$TASK" "$proj" > "$T/intake.md"
  cp "$HERE/$project/task/"* "$T/"
  cp "$HERE/$name/checks.md" "$HERE/$name/changed-files.md" "$T/"
  cp -R "$HERE/$name/checks" "$T/checks"
  if [ -n "$previous" ]; then
    mkdir -p "$T/archive/261120-100000-run1"
    cp "$HERE/$name/$previous" "$T/archive/261120-100000-run1/verify.md"
    prevline="
Previous verify: $T/archive/261120-100000-run1/verify.md"
  fi
  prompt="Call the agent my-agent:verifier exactly once with exactly this prompt, wait for it, then print the first line of $T/verify.md and stop. This is a judge test: do not invoke any skill (no /my-agent continue).

Completion criteria file: $T/scope.md
Scope change: none
Deliverable: $proj
intake: $T/intake.md
Changed files: $T/changed-files.md
Check record: $T/checks.md$prevline
Result path: $T/verify.md"
  (cd "$proj" && printf '%s\n' "$prompt" | claude -p --plugin-dir "$PLUGIN" --model haiku --max-budget-usd 2 \
      --permission-mode acceptEdits --allowedTools $FOLDER_TOOLS \
      > "$proj/run.out" 2> "$proj/run.err")
  got=$(head -1 "$T/verify.md" 2>/dev/null | sed 's/^Verdict: //; s/^ALL //')
  line=$(grep -m1 -e "^- $crit\. " "$T/verify.md" 2>/dev/null)
  [ "$got" = "$want" ] || miss="want $want, got '${got:-no verify.md}'"
  case "$line" in
    "- $crit. $wantline"*) ;;
    *) miss="${miss:+$miss; }criterion $crit line '${line:-none}' is not $wantline" ;;
  esac
  if [ -n "$reused" ]; then
    what="reused the record"
    ranline=$(awk -v ran="$reused" '/^## /{inside=($0 == "## Commands run"); next}
        inside && /^- / && index($0, ran) && index($0, "(checks.md") {print; exit}' "$T/verify.md" 2>/dev/null)
    [ -n "$ranline" ] || miss="${miss:+$miss; }no ## Commands run line holds '$reused' with (checks.md"
    ranline=$(awk -v ran="$reused" '/^## /{inside=($0 == "## Commands run"); next}
        inside && /^- / && index($0, ran) && !index($0, "(checks.md") {print; exit}' "$T/verify.md" 2>/dev/null)
    [ -z "$ranline" ] || miss="${miss:+$miss; }a ## Commands run line holds '$reused' without (checks.md (it ran the suite)"
  else
    what="ran the suite itself"
    ranline=$(awk -v ran="$ran" '/^## /{inside=($0 == "## Commands run"); next}
        inside && /^- / && index($0, ran) && !index($0, "(checks.md)") {print; exit}' "$T/verify.md" 2>/dev/null)
    [ -n "$ranline" ] || miss="${miss:+$miss; }no ## Commands run line runs '$ran' without (checks.md)"
  fi
  if [ -z "$miss" ]; then
    say "ok   $name: $want, criterion $crit $wantline, $what"
  else
    say "MISS $name: $miss (see $proj)"
    fail=1
  fi
}

fail=0
for name in "${NAMES[@]}"; do
  if is_folder "$name"; then
    run_folder "$name"
  else
    run_note "$name"
  fi
done
if [ $fail -eq 0 ]; then
  say "JUDGE OK"
  rm -rf "$WORK"
else
  say "JUDGE MISMATCH (kept $WORK)"
fi
exit $fail
