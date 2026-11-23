# Changes: in-flight revision · abort · task worktree

L1 reads this file on a change request, a profile change at the first gate, `Abort`, or `New task in a worktree` (Intake item 1) (SKILL.md "Procedure files").

## In-flight revision (before G3 acceptance)

"current rev" and "Archive" are defined in `recorder.md` "Revision records and archive". A rewrite of `plan.md` before G1b approval that keeps the confirmed scope is "Rewrite before approval" in `phases/plan.md`.

- **Profile change at the first gate** (G1a, or G1b in a small task): allowed until that gate's approval line. Procedure:
  1. To dev outside a git repository: refuse ("The dev profile needs a git repository; this task location is not one.") and popup `Keep <current profile> (Recommended)` / `Abort`; nothing changes.
  2. Archive to `archive/<time>-rev<current rev>-profile/` (the rev does not go up).
  3. Update `Profile:` in `intake.md`; `Request:` is left as written. The label is then `(set by you)` because of the `profile` run-log line.
  4. Convert. With `scope.md` (at G1a): keep it, ask only the new profile's Scope items still missing, run explorer again only if `explore.md` lacks the new profile's facts (dev: check commands), clear `## Confirmation`, archive and remove `scope-review.md`, and go back to ① Define (`back=1`), then Scope Review and G1a. Without `scope.md` (a small task at G1b): write `scope.md` from the plan's `## Scope summary` and `## Completion criteria`, ask the new profile's Scope items still missing, archive and remove `plan.md`, and go back to ① Define (`back=1`). Before any scope exists nothing is rolled back (`back=-`, `archive=-`) and the interview goes on with the new profile's items.
  5. Write the `profile` line (Recorder rules), change `phase:` in `.active`, and tell the person in one line.
     - Models preset: run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/agent-models.py" presets --profile <new profile> --data-dir "<data folder>"` again and ask with the same popup rule as Intake item 3 ("Models preset" in `new-task.md`: a popup only with 2 or more presets; one preset gives `standard`; `none` gives no `Models:` line; exit 1 gives the broken-file popup). Then replace `Models:` in `intake.md` (remove it when Intake item 3 gives none) and, when `Models:` was written, write `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" models preset=<name> source=file --data-dir "<data folder>" --task-dir "<task_dir>"`. Record the popup like the other popups of that gate.
  - After G1b approval a profile change is a new task (`Follows:`); offer `Split into a new task (Recommended)` in the kind popup below.

When a message that looks like a revision arrives after G1b approval, first ask its kind in a popup: `Revise this task` / `Adjust within approved scope` / `Split into a new task` / `Cancel` (put the one that fits first, with `(Recommended)`).

- **Adjust within approved scope:** Add a `Scope change: <content>` line under `plan.md` `## Approval` with Edit, write a `fix what="Scope change: <content>" files=plan.md` line, and continue.
  - If the person says they will do a manual check later, add `Scope change: criterion <n> is checked by the user later` under `plan.md` `## Approval` with Edit right then (the run-log line is the same).
  - Start no Verify run while an adjustment is still being built (its coder call has not returned and been merged).
- **Revise this task:** The new rev is current rev + 1.
  1. Stop new delegation (same as Abort item 1). Record finished background results with `stale` lines and set those units in `plan.md` to `stale`.
  2. Decide the phase to go back to. If WHAT/WHY changed, ① Define; if only HOW changed, ② Plan. Tell the person in one line.
  3. Archive to `archive/<time>-rev<new rev>/`.
  4. Write the `revision rev=<new rev> … state=pending` line, and add `- rev<new rev> <YYYY-MM-DD HH:MM> <what changed>; archive <path>; back to <phase>` to `## Revisions` at the very end of `plan.md` (create it if missing).
  5. Delete `plan-review.md`, `verify.md`, `review.md` and clear `## Approval` (and `Scope change:`). If going back to ①, also delete `scope-review.md` and clear `## Confirmation` in `scope.md`. Update `phase:` in `.active`. When done, write the `revision rev=<new rev> state=done` line.
  - For items 4 and 5, find each section by headings that start at the beginning of a line (`## Revisions`, `## Approval`) and edit only that section with the Edit tool. Never cut by string position, and do not overwrite the whole file with Write.
  6. Go through every gate again from that phase. For deliverables already made, architect decides keep / revise / discard in the `## Existing work` table. Before approval, delete or revert nothing.
  7. If this is the 4th revision of the same task, popup before starting it: `Keep revising (Recommended)` / `Restart as a new task` / `Abort`.
- **A request after G3 acceptance** is a new task (`Follows:`).

## Abort

When `Abort` was picked in a popup, or Intake decided to abort the previous task.

1. Start no new delegation. Wait until background subagents finish; stop a workflow with TaskStop.
2. If delegated approval is on, run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" delegate state=off how=end --data-dir "<data folder>" --task-dir "<task_dir>"`. Change `intake.md` to `Status: aborted <YYYY-MM-DD HH:MM> <reason>` and run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" abort why="<reason>" --data-dir "<data folder>" --task-dir "<task_dir>"`.
   Then run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/usage-snapshot.py" --data-dir "<data folder>" --task-dir "<task_dir>"` (saves the main session's tokens per step to `main-usage.json`; on exit 3, state the printed cause in one line and go on).
3. Run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/cd-guard.py" --remove --location "<task location>" --task "<absolute task folder>"` and show its line. Delete `.active`, and if `<data folder>/active-index.json` has a line for this task location, delete only that line.
4. Leave the task folder as is. Report the leftover worktrees and the list of uncommitted changes this task left in the main tree.
5. Popup: `Leave as is (Recommended)` / `Clean up worktrees`. Do not revert changes in the main tree.

- To do an aborted task again, create a new task and write `Follows:`.

## Task worktree

When the person picks `New task in a worktree` (Intake item 1):

1. Compute the task ID first (Intake item 4: the facts call's `date:` and `ids:` lines and the slug).
2. Make sure `.claude/worktrees/` is excluded (the `git check-ignore` / `info/exclude` step of `build.md` step 5 item 2).
3. Run `git worktree add -b my-agent-task/<task-id> <task location>/.claude/worktrees/task-<task-id>` as one command (absolute path).
4. Tell the person to open a new session in that folder and send the request again.
5. Create nothing else: no `.active`, task folder or run-log line, so the two-question popup (`qn=1`/`qn=2`) is not recorded here.
