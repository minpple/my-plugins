# Recorder: run-log commands · archive · failures

L1 reads this file before the first run-log command or delegation of a session: at Intake (read with the facts call, before the create call writes the first line) and at `continue` item 4, and again after compaction (SKILL.md "Procedure files").

## Recorder rules

The run-log is `run-log.md` in the task folder; only `run-log.py` writes its lines (it adds the time), never a direct edit. Hooks record subagent `call:`/`start:`/`stop:` and G2 `ask:`/`answer:` automatically, so L1 does not write them; an inline role's run is L1's `inline` line. Values (`q=`, `choice=`, `why=`, etc.) follow "Tool choice": the shell runs backticks and `$(`, and before approval the G1-B hook asks (the G2 dialog) for such commands. Even after approval, for a `git … commit` command with `$(` or backticks the verdict hook cannot tell whether it is a commit, so it asks (the G2 dialog) before Verify·Review. Get values by running a command separately (e.g. run `git rev-parse HEAD` first; `date` for the time). For `--model`, use the exact model ID of the current session given in the system prompt.

| When | Command |
|---|---|
| On entering each step (1B–4B; the Intake create call writes step 1A's line) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" step n=<1A–4B> name=<step name> --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"` |
| Right before a popup | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" ask gate=<G1-A/G1-B/G3/E/Q> q="<question summary>" rec="<recommended choice>" --data-dir "<data folder>" --task-dir "<task_dir>"` (`Q` for a popup that is not a gate; `rec=-` if there is no recommendation. A popup with several questions gets one `ask` per question with `qn=1`, `qn=2`, ...; a single question needs no `qn=`) |
| After the answer | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" answer gate=<same value> choice="<chosen choice>" --data-dir "<data folder>" --task-dir "<task_dir>"` (if the answer was typed in (Other), add `other=1` at the end; for a prose reply sent while the popup is pending, add `prose=1`; for an answer the person gave in advance, add `pre=1`; with several questions, add the same `qn=` as its `ask`. Do not add `(Recommended)` to choice; if present, the tally strips it before comparing) |
| The `cost` line of a moment. The `step` lines that open a phase write it themselves, and `pre-gate.py --gate G3` writes it before the G3 popup, so L1 runs no separate `cost` command: `n=1A` (`baseline=1`), `n=2A`, `n=3A` (also Back to Execute), `n=4A` (a light path without Verify writes none) and the G3 pre-gate call | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" cost --data-dir "<data folder>" --task-dir "<task_dir>"` (the script's own command; see Cost below) |
| Start of an in-flight revision (Revise this task) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" revision rev=<new rev> why="<what changed>" archive=<archive folder> to=<phase to go back to, 1 or 2> invalidated=<judgment files to delete, comma-separated> keep="<what was kept>" state=pending --data-dir "<data folder>" --task-dir "<task_dir>"` |
| In-flight revision cleanup done | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" revision rev=<new rev> state=done --data-dir "<data folder>" --task-dir "<task_dir>"` |
| Rewrite before approval (architect rewrites before G1-B) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" revision rev=<current rev> before=G1-B why="<what changed>" archive=<archive folder> --data-dir "<data folder>" --task-dir "<task_dir>"` |
| Plan edit by L1 before approval (small change: Plan Review finding or G1-B `Request changes`) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" fix what="<finding or request>" files=plan.md before=G1-B archive=<archive folder> --data-dir "<data folder>" --task-dir "<task_dir>"` |
| Delegated approval starts (message) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" delegate state=on how=message --data-dir "<data folder>" --task-dir "<task_dir>"` (by `--auto`: `how=flag`, written by the Intake create call) |
| Delegated approval ends | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" delegate state=off how=<person or end> --data-dir "<data folder>" --task-dir "<task_dir>"` (`person`: take-back message; `end`: G3 acceptance or Abort) |
| Popup answered by L1 (delegated approval or a settled popup) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" answer gate=<same value> choice="<recommended choice>" by=L1 --data-dir "<data folder>" --task-dir "<task_dir>"` (an `answer` line without `by=` is the person's) |
| Profile change at the first gate; at Intake, a profile other than the Router's pick (`back=- archive=-`) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" profile from=<old> to=<new> back=<1, 2 or -> archive=<archive folder or -> --data-dir "<data folder>" --task-dir "<task_dir>"` |
| Model preset chosen (Intake, profile change at the first gate), only when `Models:` is written | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" models preset=<name> source=file --data-dir "<data folder>" --task-dir "<task_dir>"` |
| Adjust within approved scope | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" fix what="Scope change: <content>" files=plan.md --data-dir "<data folder>" --task-dir "<task_dir>"` |
| An inline role finished | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" inline agent=my-agent:<role> unit=<u… or -> file=<result file, or - for coder> --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"` (coder adds `result=<first line of its report>`) |
| A background result becomes stale in a revision | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" stale id=<agent_id> rev=<new rev> --data-dir "<data folder>" --task-dir "<task_dir>"` |
| Execute start (dev profile) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" base commit=<git rev-parse HEAD> dirty="<git status --porcelain summary>" --data-dir "<data folder>" --task-dir "<task_dir>"` |
| A merge conflict was handled | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" merge unit=<work unit> files="<files>" how="<how it was resolved>" by=<L1 or coder> --data-dir "<data folder>" --task-dir "<task_dir>"` |
| L1 made a small fix (other than `Scope change:` above) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" fix what="<what was fixed>" files="<files>" --data-dir "<data folder>" --task-dir "<task_dir>"` |
| The deliverable was saved after G3 | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" deliver path=<saved path> --data-dir "<data folder>" --task-dir "<task_dir>"` (for a commit, `path=commit:<short sha>`) |
| Back to Execute (Verify FAIL, Review BLOCKER, G3 Rework; the G3 light path (`accept.md` item 7) skips it) | `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/back-execute.py" --task "<absolute task folder>" --units <work units> --back "<reason>" --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"` (`accept.md` "Back to Execute"; it writes the Execute step line with `back=` and `archive=`) |

Step names: 1A `Intake`, 1B `Explore-Scope`, 2A `Plan`, 2B `Plan-Review`, 3A `Execute`, 3B `Merge`, 4A `Verify`, 4B `Review-Deliver`.

Read the lines the command prints:

- `MISMATCH: …` — the configured model differs from the actual model. Tell the person in one line and continue.
  - If `MISMATCH: main session …`, L1 is not opus (the skill's `model:` applies only to the first turn). Say in one line: "The main session is <model>. By design L1 is opus, so switch with `/model opus`. Next time, open the session with `claude --model opus`." Continue even if it is not switched; do not say it again in the same task (the script prints it only once).
- `PARTIAL: <agent> <id> unit=<u…|b…> …` — that worker ended without a final answer (maxTurns, `end=partial`; not the same as the first line `PARTIAL <reason>` a worker writes itself). Handle it as "worker stopped once" (Failure handling below).
- `run-log: no active my-agent task …` — `.active` is missing or was not found. Fix `.active` first.

**Cost (for reference):** the script reads `cost_usd` from `~/.cache/claude-sessions/statusline/<session ID>.json` and writes the `cost` line itself (`reset=1` if the value fell); L1 never types a cost. Without the file it prints `run-log: no cost line (…)`, writes nothing, and L1 continues. In the G3 report, write it only as "about $N (reference, estimated at list price)", and use it for no decision.

## Popup label

Every popup L1 asks (not the G2 permission dialog) has the first line `[<step ID>] <step name> · <gate>`, the gate being `G1-A`, `G1-B`, `G3`, `E` or `Q`; the question is on the next line.

- The step name is the short English name (`Explore → Scope`, `Plan Review`, `Merge`), without the gate or other words the monitor adds, also in a popup in another language.
- A popup asked outside a step's own procedure (task start, resume, retrospective, change request) uses the step the task is in (retrospective `[4B]`). A popup asked before the task exists uses `[1A] Intake`.

## Revision records and archive

The record of revisions is the run-log's `revision` lines. `## Revisions` at the very end of `plan.md` (after `## Approval`) is a secondary record for people to read; when architect rewrites `plan.md`, it carries the section over as is. In every rule file, "current rev" is the last `rev=` in the run-log `revision` lines (0 if none). "Archive" means running `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/archive.py" --task "<absolute task folder>" --name <the name after the time, such as rev0-draft>`. It copies the whole task folder (except `archive/`) to `archive/<time>-<name>/`, compares the copy and prints that folder, which is the `archive=` value of the run-log line. On a non-zero exit, stop and report its line.

## Failure handling

| Situation | Handling |
|---|---|
| API error, rate limit | Retry once with the same model. If it happens again, E |
| Worker stopped once (`PARTIAL`, `end=partial`) | Retry on opus as a new call (never a resume) with the same input and the stop report (call argument `model: "opus"`, which beats the preset) |
| Background research: a researcher stops, or reports `DONE` without a valid note | The `b<n>` is the unit: the rows above and below apply to it (`unit=b<n>`); a second stop of the same `b<n>` is E |
| Worker stopped twice | If it is a small fix L1 can make directly, make it; otherwise E. If the plan was wrong, go back to Plan |
| Verify FAIL 1–2 times | Archive the judgment files, go back to Execute, and pass the list of failed criteria (`accept.md` "Back to Execute"); after the second FAIL on the same criterion, the fixer's new call must give a structural argument (why no other failing form remains) before the fix, or offer `Change scope` through E |
| Verify FAIL 3 times in a row | E: `Give direction` / `Change scope` / `Abort` |
| A workflow ends as completed | Do not treat it as success until you check its "could not handle" list |

**Model and effort per call:** they come from the task's preset. Before G1-B approval run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/agent-models.py" show --profile <p> --preset <name> --data-dir "<data folder>"`; after approval run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/agent-models.py" show --plan <task folder>/plan.md` (the `## Models` rows). Pass the Agent call arguments `model`/`effort` only for the fields listed under `pass=`. With no `Models:` line, pass none. When `continue` reported the preset gone (`continue` item 4), do not run `show --plan` and pass none for the rest of the task. The retry on opus passes `model: "opus"` for that call and beats the preset; an `effort` listed under `pass=` is still passed. A role whose line shows `pass=inline` gets no Agent call ("Inline role").
