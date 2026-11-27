#!/bin/sh
# Live probe of parallel coders in unit copies (scope criteria 14 and 15). Run by hand, never by the test suite:
# one run starts two real `claude -p` sessions and spends API credit (cap below).
#
# usage: copy-probe.sh <evidence folder>
#
# One session per location: a new temp folder that is a git repository ("git") and a new plain temp folder ("nongit").
# Each session runs this working copy of the plugin (--plugin-dir) and calls 2 `my-agent:coder` agents in one message
# (4 coders per run). Each coder makes three Write calls as parallel calls in one message: its own copy, the main tree, the other copy.
# The guard must allow the first and deny the other two. Then the session's second user message is `/cd <copy of u1>`
# (`Cd(...)` governs `/cd` and a host's move request, never a Bash `cd`).
#
# Only this working copy's hooks judge the run: `--setting-sources project,local` leaves out the user settings that
# enable an installed my-agent plugin, and `--plugin-dir` loads the working copy. The task's `Cd(...)` rule is in the
# location's `.claude/settings.local.json` (local source), written by worktree.py create before the session starts.
# Nothing is written under ~/.claude* beyond what a `claude -p` run writes itself.
# Evidence: <evidence folder>/<git|nongit>/ and <evidence folder>/summary.txt (ends with one `result:` line).
set -u

# cap of one session; a run has two
BUDGET_USD_PER_SESSION=${COPY_PROBE_BUDGET_USD:-2.00}

HERE=$(cd "$(dirname "$0")" && pwd -P)
PLUGIN=$(cd "$HERE/../.." && pwd -P)
WORKTREE_PY="$PLUGIN/l4-tools-guards/scripts/worktree.py"
HOOK_PY="$HERE/copy-probe-hook.py"
TASK_ID=261127-copy-probe

[ $# -eq 1 ] && [ -n "$1" ] || { echo "usage: copy-probe.sh <evidence folder>"; exit 2; }
mkdir -p "$1" || { echo "copy-probe: cannot create the evidence folder $1"; exit 2; }
EVID=$(cd "$1" && pwd -P)

HELP=$(claude --help 2>&1)
case $HELP in
  *--max-budget-usd*) ;;
  *) echo "copy-probe: this claude has no --max-budget-usd, so no capped run is possible; no session started"; exit 2 ;;
esac
CAP_RUN=$(awk -v b="$BUDGET_USD_PER_SESSION" 'BEGIN { printf "%.2f", 2 * b }')
echo "copy-probe: 2 sessions (git, nongit), 2 coders each, cap $BUDGET_USD_PER_SESSION USD per session ($CAP_RUN USD per run)"
case $HELP in
  *--input-format*) FMT="--input-format stream-json --output-format stream-json --verbose" ;;
  *) FMT="--output-format stream-json --verbose" ;;   # no /cd can be sent: cd move is not driven
esac

export MA_TASK_DIR=.my-agent
export GIT_AUTHOR_NAME=probe GIT_AUTHOR_EMAIL=probe@example.invalid GIT_COMMITTER_NAME=probe GIT_COMMITTER_EMAIL=probe@example.invalid
SUMMARY="$EVID/summary.txt"
: > "$SUMMARY"
FAILS=""

say() { echo "$*" >> "$SUMMARY"; }
fail() { FAILS="$FAILS $1"; say "FAIL $1"; }

json_text() { awk 'BEGIN { ORS = "\\n" } { gsub(/"/, "\\\""); print }'; }

# coder_prompt <unit> <own copy> <main tree> <other copy>: first line `Work unit:`, second line `Worktree:`
coder_prompt() {
  printf 'Work unit: %s probe\nWorktree: %s\n' "$1" "$2"
  printf 'Make exactly three Write calls as three parallel tool calls in ONE message, with no tool call before that message:\n'
  printf '1. Write %s/probe-%s.txt with the content own\n' "$2" "$1"
  printf '2. Write %s/probe-main-%s.txt with the content main\n' "$3" "$1"
  printf '3. Write %s/probe-from-%s.txt with the content other\n' "$4" "$1"
  printf 'Writes 2 and 3 are expected to be refused by the guard; that is the point of this probe. All three are sent together, so a refusal of one Write does not cancel the others; do not try another way around a refusal.\n'
  printf 'Report each result in one line. Then end with DONE.\n'
}

# first_message <main tree> <copy u1> <copy u2>
first_message() {
  {
    printf 'Call the Agent tool twice in ONE message (two parallel calls), subagent_type my-agent:coder, and nothing else.\n'
    printf 'The prompt of each call is the text between its BEGIN and END lines, copied exactly, line by line.\n'
    printf 'BEGIN u1\n'; coder_prompt u1 "$2" "$1" "$3"; printf 'END u1\n'
    printf 'BEGIN u2\n'; coder_prompt u2 "$3" "$1" "$2"; printf 'END u2\n'
    printf 'When both calls are back, reply with their reports and stop.\n'
  }
}

# feed <first message text> <move command>: the move is sent after the first turn's result
feed() {
  if [ "$FMT" = "${FMT#--input-format}" ]; then
    printf '%s\n' "$1"
    return 0
  fi
  printf '{"type":"user","message":{"role":"user","content":"%s"}}\n' "$(printf '%s\n' "$1" | json_text)"
  n=0
  while ! grep -q '"type":"result"' "$OUT" 2>/dev/null && [ "$n" -lt 900 ]; do sleep 1; n=$((n + 1)); done
  printf '{"type":"user","message":{"role":"user","content":"%s"}}\n' "$2"
}

# prepare <kind>: temp location, task, create two copies
prepare() {
  kind=$1; dir="$EVID/$kind"; mkdir -p "$dir"
  loc=$(mktemp -d) && loc=$(cd "$loc" && pwd -P)
  echo "$loc" > "$dir/location.txt"
  if [ "$kind" = git ]; then
    git -C "$loc" init -q && echo probe > "$loc/README.md" && git -C "$loc" add README.md && git -C "$loc" commit -q -m probe || return 1
  else
    echo probe > "$loc/README.md"
  fi
  task="$loc/.my-agent/$TASK_ID"
  mkdir -p "$task/work" || return 1
  printf 'task: %s\nphase: execute\nsession:\nstarted: 2026-11-27 10:00\n' "$TASK_ID" > "$loc/.my-agent/.active"
  printf '# Intake\n\nProbe task.\n' > "$task/intake.md"
  printf '# Plan: %s\n\n## Work units\n\n### u1 probe\n- Agent: `my-agent:coder`\n\n### u2 probe\n- Agent: `my-agent:coder`\n\n## Approval\n\nApproved 2026-11-27 10:00\n' "$TASK_ID" > "$task/plan.md"
  python3 "$WORKTREE_PY" create --location "$loc" --task "$task" --unit u1 --unit u2 > "$dir/create.txt" 2>&1
  rc=$?
  cat "$dir/create.txt" >> "$SUMMARY"
  [ "$rc" -eq 0 ] || return 1
  copy1="$loc/.claude/worktrees/my-agent-$TASK_ID-u1"
  copy2="$loc/.claude/worktrees/my-agent-$TASK_ID-u2"
  cat > "$dir/settings.json" <<JSON
{"hooks":{"PreToolUse":[{"hooks":[{"type":"command","command":"python3 $HOOK_PY","timeout":15}]}]}}
JSON
}

# judge <kind>: summary lines for the cases of both coders, the cd move and the cost
judge() {
  kind=$1; dir="$EVID/$kind"; loc=$(cat "$dir/location.txt"); out="$dir/output.json"
  # attempted <path> <unit>: the hook log holds a Write by that unit's coder to that path
  attempted() { grep -F "\"path\": \"$1\"" "$dir/hook-log.jsonl" 2>/dev/null | grep -F "\"unit\": \"$2\"" | grep -q '"tool": "Write"'; }
  # denied_in_run_log <path>: a guard deny line names that path
  denied_in_run_log() { grep -F "$1" "$dir/guard-lines.txt" 2>/dev/null | grep -q 'decision=deny'; }
  copy1="$loc/.claude/worktrees/my-agent-$TASK_ID-u1"
  copy2="$loc/.claude/worktrees/my-agent-$TASK_ID-u2"
  { echo "files in main tree:"; (cd "$loc" && find . -path ./.git -prune -o -path "./.claude" -prune -o -type f -print | sort)
    echo "files in copy u1:"; (cd "$copy1" && find . -path ./.git -prune -o -type f -print | sort)
    echo "files in copy u2:"; (cd "$copy2" && find . -path ./.git -prune -o -type f -print | sort); } > "$dir/files.txt" 2>&1
  grep 'guard' "$loc/.my-agent/$TASK_ID/run-log.md" > "$dir/guard-lines.txt" 2>/dev/null
  grep -o '"total_cost_usd":[0-9.e-]*' "$out" 2>/dev/null | tail -n 1 > "$dir/cost.txt"
  say "$kind cost: $(cat "$dir/cost.txt" 2>/dev/null || true)"
  grep -q '"type":"result"' "$out" 2>/dev/null || fail "$kind:session-not-finished"
  for u in u1 u2; do
    if [ "$u" = u1 ]; then own=$copy1; other=$copy2; else own=$copy2; other=$copy1; fi
    log="$dir/hook-log.jsonl"
    # parallel Writes: the hook's "first" marker can land on any of the three, so any Write of this unit and copy counts
    first=$(grep '"first": true' "$log" 2>/dev/null | grep "\"unit\": \"$u\"" | grep "\"worktree\": \"$own\"" | grep -c '"tool": "Write"')
    if [ "$first" -ge 1 ]; then say "$kind $u first-call: pass (unit and Worktree: read at the first tool call, a Write)"
    else fail "$kind:$u:first-call"; fi
    # a write case passes only with evidence: the Write attempt in the hook log; the denied cases also need a guard deny line naming the path
    case=own-copy-write; p="$own/probe-$u.txt"
    if ! attempted "$p" "$u"; then say "$kind $u $case: not attempted"; fail "$kind:$u:$case:not-attempted"
    elif [ -f "$p" ]; then say "$kind $u $case: pass"
    else fail "$kind:$u:$case"; fi
    case=main-tree-write; p="$loc/probe-main-$u.txt"
    if ! attempted "$p" "$u"; then say "$kind $u $case: not attempted"; fail "$kind:$u:$case:not-attempted"
    elif [ ! -e "$p" ] && denied_in_run_log "$p"; then say "$kind $u $case: pass (denied)"
    else fail "$kind:$u:$case"; fi
    case=other-copy-write; p="$other/probe-from-$u.txt"
    if ! attempted "$p" "$u"; then say "$kind $u $case: not attempted"; fail "$kind:$u:$case:not-attempted"
    elif [ ! -e "$p" ] && denied_in_run_log "$p"; then say "$kind $u $case: pass (denied)"
    else fail "$kind:$u:$case"; fi
  done
  if [ "$FMT" = "${FMT#--input-format}" ]; then move=notdriven
  elif grep -qF 'excluded by the Cd(' "$out" 2>/dev/null; then move=refused
  elif grep -qF "\"cwd\":\"$copy1\"" "$out" 2>/dev/null; then move=moved
  else move=notdriven; fi
  case $move in
    refused) say "$kind cd move: refused" ;;
    moved) say "$kind cd move: moved"; fail "$kind:cd-move-moved"
      say "open risk: the Cd rule was in $loc/.claude/settings.local.json before the session started; check whether this session applied it" ;;
    *) say "$kind cd move: not driven; open a session in $loc and type: /cd $copy1" ;;
  esac
  if [ "$move" = notdriven ]; then
    say "$kind kept: $loc (Cd rule on, copy u1 present)"   # left as it is: the person's typed move completes the case
  else
    python3 "$WORKTREE_PY" remove --location "$loc" --task "$loc/.my-agent/$TASK_ID" --unit u1 >> "$dir/cleanup.txt" 2>&1
    python3 "$WORKTREE_PY" remove --location "$loc" --task "$loc/.my-agent/$TASK_ID" --unit u2 >> "$dir/cleanup.txt" 2>&1
    python3 "$WORKTREE_PY" cleanup --location "$loc" --task "$loc/.my-agent/$TASK_ID" >> "$dir/cleanup.txt" 2>&1
    rm -rf "$loc"
  fi
}

run_kind_prepare() {
  prepare "$1" || { fail "$1:setup"; return 1; }
  return 0
}

# --- git location
if run_kind_prepare git; then
  d="$EVID/git"; loc=$(cat "$d/location.txt"); OUT="$d/output.json"; export OUT COPY_PROBE_LOG="$d/hook-log.jsonl"
  msg=$(first_message "$loc" "$loc/.claude/worktrees/my-agent-$TASK_ID-u1" "$loc/.claude/worktrees/my-agent-$TASK_ID-u2")
  cd "$loc" && feed "$msg" "/cd $loc/.claude/worktrees/my-agent-$TASK_ID-u1" | claude -p --plugin-dir "$PLUGIN" --setting-sources project,local --settings "$d/settings.json" --permission-mode acceptEdits --max-budget-usd "$BUDGET_USD_PER_SESSION" $FMT > "$OUT" 2> "$d/stderr.txt"
  cd "$EVID"; judge git
fi

# --- non-git location
if run_kind_prepare nongit; then
  d="$EVID/nongit"; loc=$(cat "$d/location.txt"); OUT="$d/output.json"; export OUT COPY_PROBE_LOG="$d/hook-log.jsonl"
  msg=$(first_message "$loc" "$loc/.claude/worktrees/my-agent-$TASK_ID-u1" "$loc/.claude/worktrees/my-agent-$TASK_ID-u2")
  cd "$loc" && feed "$msg" "/cd $loc/.claude/worktrees/my-agent-$TASK_ID-u1" | claude -p --plugin-dir "$PLUGIN" --setting-sources project,local --settings "$d/settings.json" --permission-mode acceptEdits --max-budget-usd "$BUDGET_USD_PER_SESSION" $FMT > "$OUT" 2> "$d/stderr.txt"
  cd "$EVID"; judge nongit
fi

if [ -z "$FAILS" ]; then echo "result: pass" >> "$SUMMARY"; else echo "result: fail:$FAILS" >> "$SUMMARY"; fi
tail -n 1 "$SUMMARY"
[ -z "$FAILS" ]
