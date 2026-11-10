# Recorder: run-log commands · archive · failures

L1 reads this file before the first run-log command or delegation of a session: at Intake item 10 and at `continue` item 4, and again after compaction (SKILL.md "Procedure files").

## Recorder rules

The run-log is `run-log.md` in the task folder, and only `run-log.py` writes its lines. Do not edit it directly. The script adds the time. Hooks record subagent `call:`/`start:`/`stop:` and G2 `ask:`/`answer:` automatically, so L1 does not write them; an inline role's run is L1's `inline` line. Values (`q=`, `choice=`, `why=`, etc.) follow "Tool choice": the shell runs backticks and `$(`, and before approval the G1b hook asks (the G2 dialog) for such commands. Even after approval, for a `git … commit` command with `$(` or backticks the verdict hook cannot tell whether it is a commit, so it asks (the G2 dialog) before Verify·Review. Get values by running a command separately (e.g. run `git rev-parse HEAD` first). If you need the time, run `date` first and write the value. For `--model`, use the exact model ID of the current session given in the system prompt.

| When | Command |
|---|---|
| On entering each step (1–8) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" step n=<1-8> name=<step name> --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"` |
| Right before a popup | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" ask gate=<G1a/G1b/G3/E/Q> q="<question summary>" rec="<recommended choice>" --data-dir "<data folder>" --task-dir "<task_dir>"` (`Q` for a popup that is not a gate; `rec=-` if there is no recommendation. A popup with several questions gets one `ask` per question with `qn=1`, `qn=2`, ...; a single question needs no `qn=`) |
| After the answer | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" answer gate=<same value> choice="<chosen choice>" --data-dir "<data folder>" --task-dir "<task_dir>"` (if the answer was typed in (Other), add `other=1` at the end; for a prose reply sent while the popup is pending, add `prose=1`; for an answer the person gave in advance, add `pre=1`; with several questions, add the same `qn=` as its `ask`. Do not add `(Recommended)` to choice; if present, the tally strips it before comparing) |
| At Intake the `step n=1` line writes it itself (`baseline=1`); L1 runs it on a phase change (right after the step line that opens the phase), at the start of Verify (after its step line) and right before the G3 popup; when two of these moments coincide (the phase change into ④ Accept is the start of Verify), one cost line is enough | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" cost --data-dir "<data folder>" --task-dir "<task_dir>"` (see Cost below) |
| Start of an in-flight revision (Revise this task) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" revision rev=<new rev> why="<what changed>" archive=<archive folder> to=<phase to go back to, 1 or 2> invalidated=<judgment files to delete, comma-separated> keep="<what was kept>" state=pending --data-dir "<data folder>" --task-dir "<task_dir>"` |
| In-flight revision cleanup done | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" revision rev=<new rev> state=done --data-dir "<data folder>" --task-dir "<task_dir>"` |
| Rewrite before approval (architect rewrites before G1b) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" revision rev=<current rev> before=G1b why="<what changed>" archive=<archive folder> --data-dir "<data folder>" --task-dir "<task_dir>"` |
| Plan edit by L1 before approval (small change: Plan Review finding or G1b `Request changes`) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" fix what="<finding or request>" files=plan.md before=G1b archive=<archive folder> --data-dir "<data folder>" --task-dir "<task_dir>"` |
| Delegated approval starts (message) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" delegate state=on how=message --data-dir "<data folder>" --task-dir "<task_dir>"` (by `--auto`: `how=flag`, Intake item 10) |
| Delegated approval ends | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" delegate state=off how=<person or end> --data-dir "<data folder>" --task-dir "<task_dir>"` (`person`: take-back message; `end`: G3 acceptance or Abort) |
| Popup answered by L1 (delegated approval) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" answer gate=<same value> choice="<recommended choice>" by=L1 --data-dir "<data folder>" --task-dir "<task_dir>"` (an `answer` line without `by=` is the person's) |
| Profile change at the first gate | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" profile from=<old> to=<new> back=<1, 2 or -> archive=<archive folder or -> --data-dir "<data folder>" --task-dir "<task_dir>"` |
| Model preset chosen (Intake, profile change at the first gate), only when `Models:` is written | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" models preset=<name> source=file --data-dir "<data folder>" --task-dir "<task_dir>"` |
| Adjust within approved scope | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" fix what="Scope change: <content>" files=plan.md --data-dir "<data folder>" --task-dir "<task_dir>"` |
| An inline role finished | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" inline agent=my-agent:<role> unit=<u… or -> file=<result file, or - for coder> --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"` (coder adds `result=<first line of its report>`) |
| A background result becomes stale in a revision | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" stale id=<agent_id> rev=<new rev> --data-dir "<data folder>" --task-dir "<task_dir>"` |
| Execute start (dev profile) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" base commit=<git rev-parse HEAD> dirty="<git status --porcelain summary>" --data-dir "<data folder>" --task-dir "<task_dir>"` |
| A merge conflict was handled | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" merge unit=<work unit> files="<files>" how="<how it was resolved>" by=<L1 or coder> --data-dir "<data folder>" --task-dir "<task_dir>"` |
| L1 made a small fix (other than `Scope change:` above) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" fix what="<what was fixed>" files="<files>" --data-dir "<data folder>" --task-dir "<task_dir>"` |
| The deliverable was saved after G3 | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" deliver path=<saved path> --data-dir "<data folder>" --task-dir "<task_dir>"` (for a commit, `path=commit:<short sha>`) |
| Back to Execute (Verify FAIL, Review BLOCKER, G3 Rework) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" step n=5 name=Execute back="<reason>" archive=<archive folder> --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"` (`accept.md` "Back to Execute") |

Step names: 1 `Intake`, 2 `Explore-Scope`, 3 `Plan`, 4 `Plan-Review`, 5 `Execute`, 6 `Merge`, 7 `Verify`, 8 `Review-Deliver`.

Read the lines the command prints:

- `MISMATCH: …` — the configured model differs from the actual model. Tell the person in one line and continue.
  - If `MISMATCH: main session …`, L1 is not opus (the skill's `model:` applies only to the first turn). Say in one line: "The main session is <model>. By design L1 is opus, so switch with `/model opus`. Next time, open the session with `claude --model opus`." Continue even if it is not switched. Do not say it again in the same task (the script also prints it only once).
- `PARTIAL: <agent> <id> unit=<u…> …` — that worker ended without a final answer (maxTurns, `end=partial`; not the same as the first line `PARTIAL <reason>` a worker writes itself). Handle it as "worker stopped once" (Failure handling below).
- `run-log: no active my-agent task …` — `.active` is missing or was not found. Fix `.active` first.

**Cost (for reference):** the script reads `cost_usd` from `~/.cache/claude-sessions/statusline/<session ID>.json` and writes the `cost` line itself (`reset=1` if the value fell); L1 never types a cost. If the file is missing it prints `run-log: no cost line (…)`, writes nothing, and L1 continues. In the G3 report, write it only as "about $N (reference, estimated at list price)", and use it for no decision.

## Revision records and archive

The record of revisions is the run-log's `revision` lines. `## Revisions` at the very end of `plan.md` (after `## Approval`) is a secondary record for people to read; when architect rewrites `plan.md`, it carries the section over as is. In every rule file, "current rev" is the last `rev=` in the run-log `revision` lines (0 if none). "Archive" means copying the whole task folder (except `archive/`) to `archive/<name>/` with `cp -pR` and comparing all of it with `cmp`. If the comparison differs, stop and report. Use absolute paths without `cd` for `mkdir`·`cp` ("Tool choice"). Get the time in the name by running `date +%y%m%d-%H%M%S` first.

## Failure handling

| Situation | Handling |
|---|---|
| API error, rate limit | Retry once with the same model. If it happens again, E |
| Worker stopped once (`PARTIAL`, `end=partial`) | Retry on opus as a new call (never a resume) with the same input and the stop report (call argument `model: "opus"`, which beats the preset) |
| Worker stopped twice | If it is a small fix L1 can make directly, make it; otherwise E. If the plan was wrong, go back to Plan |
| Verify FAIL 1–2 times | Archive the judgment files, go back to Execute, and pass the list of failed criteria (`accept.md` "Back to Execute"); after the second FAIL on the same criterion, the fixer's new call must give a structural argument (why no other failing form remains) before the fix, or offer `Change scope` through E |
| Verify FAIL 3 times in a row | E: `Give direction` / `Change scope` / `Abort` |
| A workflow ends as completed | Do not treat it as success until you check its "could not handle" list |

**Model and effort per call:** they come from the task's preset. Before G1b approval run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/agent-models.py" show --profile <p> --preset <name> --data-dir "<data folder>"`; after approval run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/agent-models.py" show --plan <task folder>/plan.md` (the `## Models` rows). Pass the Agent call arguments `model`/`effort` only for the fields listed under `pass=`. With no `Models:` line, pass none. When `continue` reported the preset gone (`continue` item 4), do not run `show --plan` and pass none for the rest of the task. The retry on opus passes `model: "opus"` for that call and beats the preset; an `effort` listed under `pass=` is still passed. A role whose line shows `pass=inline` gets no Agent call ("Inline role").
