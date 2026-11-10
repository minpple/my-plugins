# New task: Flags · Intake · Task worktree

L1 reads this file when a new task starts, before Intake item 1 (SKILL.md "Procedure files"). `continue`, `status` and a phase rerun read it only for a flag problem.

## Flags

Check the leading words of the argument before Intake item 1. Leading words that start with `--` are flags (`--auto` and the profile flags); a `--dev` or `--auto` later in the request is part of the request text. A leading em dash (`—dev`, macOS autocorrect of `--`) is read as `--`.

- Valid: exactly one of `--general`, `--research`, `--dev` (lowercase), `--auto` alone, or `--auto` with one profile flag in either order, followed by a request.
- Invalid: a name that does not exist (`--foo`), a different case (`--Dev`, `--Auto`), two profile flags, `--auto` twice, or a flag before `continue`, `status` or a phase name. Show the valid flags and popup: `Let the Router pick (Recommended)` / `Abort`. `Let the Router pick` drops every flag, `--auto` included, and treats the rest as a call without flags (`continue` runs `continue`; an empty rest shows the no-argument popup).
- Valid flags with no request: popup with the question "Type the request in the Other field": `Type the request in Other (Recommended)` / `Abort`. Read the request from the Other field, then start the new task with those flags.
- In these three popups, `Abort` stops the call and creates nothing.
- `Request:` keeps the leading flags as written. The label rule looks for a profile flag among the leading flags.
- Record these popups only when a new task starts, in Intake item 10 with the item 1–5 popups, as `ask gate=Q … rec=…` / `answer gate=Q …` lines. Always give `rec=`; do not start the `q=` value with `--` (e.g. `q="dev flag outside a git repository"`). After `Let the Router pick` leads to `continue` or `status`, write none.

## Intake (step 1, Router)

Do these in order. If any item fails, show the reason and ask in a popup: `Retry (Recommended)` / `Abort`.

1. **Task already running:** If `.active` exists in a task location candidate (item 2), popup: `Continue it (Recommended)` / `Abort that task and start new` / `Cancel`. If the task location is a git repository, add the choice `New task in a worktree` ("Task worktree" below). If `git status --porcelain` shows changes outside `<task_dir>/`, ask about them as a second question in the same popup. Continue it runs `continue`; abort first finishes "Abort" in `changes.md`. A valid profile flag in the call applies only if the person picks `Abort that task and start new`; with `Continue it` or `Cancel` the flag is ignored.
2. **Task location:**
   - If run inside a git repository, it is that repository's root (`git rev-parse --show-toplevel`). Do not ask.
   - Otherwise, popup every time: `<data folder> (Recommended)` / `Current folder` / `Other path`. For `Other path`, show one more popup that asks for the path in the Other field.
   - If the request names an existing file or skill outside the data folder, offer that file's folder (its git root if any) first with `(Recommended)`.
   - The task folder is `<task location>/<task_dir>/<task-id>/`.
   - Then do the **Git check** (every profile; below item 11).
3. **Profile:** If the call has a valid profile flag (Flags), use that profile; the Router does not pick. If the flag is `--dev` and the task location is not a git repository, popup with the reason: `Proceed as general (Recommended)` / `Abort` (`Abort` stops the call and creates nothing). After `Proceed as general`, `Request:` in `intake.md` keeps `--dev` as its first word while `Profile:` is general, and the label is `(set by you)`. Without a flag, the Router picks it from the request and does not ask. Show it in the Intake report and first gate popup with `(set by you)` if a profile flag is among the leading flags of `Request:` in `intake.md` or the run-log has a `profile` line (also after `continue`), otherwise `(Router)`; a revision changes it, see "Profile change at the first gate" in `changes.md`. The rules below are for the Router's pick:
   - `dev`: requests that change code in a git repository (feature, bug fix, refactoring). The deliverable is a commit. If the task location is not a git repository, do not pick `dev`; pick `general` and write the reason in the Intake report.
   - `research`: requests to research a topic into a note or report with sources (mainly web research).
   - `general`: any other multi-step task.
   - **Models preset:** see "Models preset" below item 11.
4. **Task ID:** `<YYMMDD>-<slug>`. Set the date once with `date +%y%m%d`. The slug is 2–4 English words for the request without the profile flag: lowercase letters, digits and hyphens, 30 characters or fewer. If the same folder exists, add `-b`, `-c`. Do not ask; show it in the first gate popup.
5. **`.gitignore`:** Only when the task location is a git repository and `<task_dir>/.gitignore` does not exist, popup: `Don't commit (Recommended)` / `Commit`. Skip it also when `git check-ignore -q <task location>/<task_dir>/` exits 0. The question says what `Commit` means: task records go into the project's commits. For Don't commit, write the line `*`; for Commit, the line `# my-agent: commit`.
6. **`.active` and index:** Create the task folder. Run `date '+%Y-%m-%d %H:%M'` first, then write the four lines of `.active` (`phase: 1`, `started:` with that value) with the Write tool, without command substitution. If the task location differs from the folder you ran in (or its git root), add one line to `<data folder>/active-index.json` (`{"<run folder>": "<task location>"}`). Keep other lines.
7. **Project list:** If `<data folder>/projects.txt` lacks the task location's absolute path, add one line. Never delete lines.
8. **Monitor:** Run `python3 "${CLAUDE_PLUGIN_ROOT}/monitor/monitor-up.py" --data-dir "<data folder>" --task-dir "<task_dir>"` and put its one output line in the Intake report as `Monitor: <line>`. If it does not start, write only `Monitor: not started (<reason>)` and continue; `"autostart": false` in `<data folder>/monitor-config.json` gives the reason `autostart off`. Do not record it in the run-log.
9. **`intake.md`:** Write it in the task folder.

   ```text
   Status: active
   my-agent: <value of git -C "${CLAUDE_PLUGIN_ROOT}" log -1 --format=%h -- ., plus -dirty if git -C "${CLAUDE_PLUGIN_ROOT}" status --porcelain -- . prints any line, none if there is no commit>
   Location: <task location>
   Profile: <general | research | dev>
   Task: <task-id>
   Request: <the request as written, one line; keep the leading valid flags as written, drop invalid flags the person let the Router replace>
   ```

   For a follow-up task, add `Follows: <previous task ID>`. When the preset file is valid and has presets for the profile, add `Models: <preset>` (Intake item 3).
10. **Record:** Read `${CLAUDE_PLUGIN_ROOT}/l1-orchestration/recorder.md` first. Then `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" step n=1 name=Intake --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"`. Record the profile-flag popups (Flags) and the popups shown in items 1–5 as `ask`/`answer` lines after this line (they could not be recorded then, because `.active` did not exist). With a statusline file, the `step n=1` line also writes the baseline `cost` line (`baseline=1`). With `--auto`, then write `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" delegate state=on how=flag --data-dir "<data folder>" --task-dir "<task_dir>"`. Delegation covers popups after that line; the item 1–5 popups and the flag popups go to the person. Last, only when `Models:` was written, run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" models preset=<name> source=file --data-dir "<data folder>" --task-dir "<task_dir>"`.
11. **Report:** Show the task ID, task location, profile (with `(set by you)` or `(Router)`) monitor line, plus the git line (`Git: <branch>, clean` or `Git: <branch>, <n> uncommitted`) only when the Git check ran, plus the line `Task folder: <task_dir>` only when it is not `.my-agent`, and the line `Delegated approval: on (--auto)` only when it is on, in 7 lines or fewer, then go to step 2 in `define.md`.

**Git check (item 2)** — Once the location is set, in every profile, run `git -C "<task location>" rev-parse --is-inside-work-tree`. Only when it prints `true` (a local git repository), run `git -C "<task location>" status --porcelain` and `git -C "<task location>" branch --show-current`, one call each, no `$(`. Anything else (the command fails or prints `false`): skip the whole check, ask nothing and show no `Git:` line. Count the uncommitted changes outside `<task_dir>/` (derived files such as `*.pyc`, `__pycache__/` or build outputs do not count). Popup only for a problem: uncommitted changes (not when item 1 already asked about them), a detached HEAD (empty branch name), or the branch `main` or `master`. The question lists the problems (up to 10 paths) and the advice: commit or stash the changes, or switch to a work branch, so a commit of this task holds only its own changes. Choices: `Fix it first (Recommended)` / `Proceed as is` / `Abort` (`Abort` stops the call and creates nothing). After `Fix it first`, repeat the check when the person says it is done. No problem: no popup. Item 11 shows the result in its `Git:` line.

**Models preset (item 3)** — after the profile is set, run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/agent-models.py" presets --profile <profile> --data-dir "<data folder>"`. Only when it prints 2 or more presets, popup (a popup of items 1–5, so it goes to the person; record it in item 10): the question opens with one plain line saying what a preset is, one choice per output line, the first line `(Recommended)`, 2–4 choices. One preset or `none`: no popup; with one preset `standard` is used. Exit 1: show the one-line cause and popup `Use definition values (Recommended)` / `Abort`; after `Use definition values` there is no `Models:` line and no `models` line, the same as a missing file.

## Task worktree

When the person picks `New task in a worktree` (Intake item 1):

1. Compute the task ID first (Intake item 4's date and slug).
2. Make sure `.claude/worktrees/` is excluded (the `git check-ignore` / `info/exclude` step of `build.md` step 5 item 2).
3. Run `git worktree add -b my-agent-task/<task-id> <task location>/.claude/worktrees/task-<task-id>` as one command (absolute path, "Tool choice").
4. Tell the person to open a new session in that folder and send the request again.
5. Create nothing else: no `.active`, no task folder, no run-log line. The two-question popup is recorded (`qn=1`/`qn=2`) only when the new task's run-log exists (Intake item 10 of that session); here nothing is recorded.
