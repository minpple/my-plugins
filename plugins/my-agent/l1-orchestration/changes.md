# Changes: in-flight revision · abort · task worktree

L1 reads this file on a change request, a profile change at the first gate, `Abort`, or `New task in a worktree` (Intake item 1) (SKILL.md "Procedure files"). L1 also reads this file for a `[plan]` review finding, by the pointer in `accept.md` step 4B.

## In-flight revision (before G3 acceptance)

"current rev" and "Archive" are defined in `recorder.md` "Revision records and archive". A rewrite of `plan.md` before G1-B approval that keeps the confirmed scope is "Rewrite before approval" in `phases/plan.md`.

- **Profile change at the first gate** (G1-A, or G1-B in a small task): allowed until that gate's approval line. Procedure:
  1. To dev outside a git repository: refuse ("The dev profile needs a git repository; this task location is not one.") and popup `Keep <current profile> (Recommended)` / `Abort`; nothing changes.
  2. Archive to `archive/<time>-rev<current rev>-profile/` (the rev does not go up).
  3. Update `Profile:` in `intake.md`; `Request:` is left as written. The label is then `(set by you)` because of the `profile` run-log line.
  4. Convert. With `scope.md` (at G1-A): keep it, ask only the new profile's Scope items still missing, run explorer again only if `explore.md` lacks the new profile's facts (dev: check commands), clear `## Confirmation`, archive and remove `scope-review.md`, and go back to ① Define (`back=1`), then Scope Review and G1-A. Without `scope.md` (a small task at G1-B): write `scope.md` from the plan's `## Scope summary` and `## Completion criteria`, ask the new profile's Scope items still missing, archive and remove `plan.md`, and go back to ① Define (`back=1`). Before any scope exists nothing is rolled back (`back=-`, `archive=-`) and the interview goes on with the new profile's items.
  5. Write the `profile` line (Recorder rules), change `phase:` in `.active`, and tell the person in one line.
     - Models preset: run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/agent-models.py" presets --profile <new profile> --data-dir "<data folder>"` again and ask with the same popup rule as Intake item 3 ("Models preset" in `new-task.md`: a popup only with 2 or more presets; one preset gives `standard`; `none` gives no `Models:` line; exit 1 gives the broken-file popup). Then replace `Models:` in `intake.md` (remove it when Intake item 3 gives none) and, when `Models:` was written, write `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" models preset=<name> source=file --data-dir "<data folder>" --task-dir "<task_dir>"`. Record the popup like the other popups of that gate.
  - After G1-B approval a profile change is a new task (`Follows:`); offer `Split into a new task (Recommended)` in the kind popup below.

When a message that looks like a revision arrives after G1-B approval, first ask its kind in a popup: `Revise this task` / `Adjust within approved scope` / `Split into a new task` / `Cancel` (put the one that fits first, with `(Recommended)`).

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

### Plan findings (Review)

`[plan]` marks a finding whose fix needs a change to the plan's approach, work units or target files.

1. **When:** before any fix of a round that sends back a `[plan]` finding: the BLOCKERs of `accept.md` step 4B item 3, or the items a G3 Rework sends back at item 7 (picked, all open items, or a set that would take the light path). The popup comes before the small fix, the light path or "Back to Execute", also when the marked fix is small.
   - A finding is marked only when, on its `review.md` line, the exact lower-case token `[plan]` stands right before `[criterion …]` (BLOCKER, SHOULD-FIX) or right before `(new)`/`(carried)` (NITPICK). The token anywhere else, such as quoted in the problem text, reads as unmarked.
   - A marked item that is not sent back (taken, or not picked) gets no popup and stays an open item.
   - A shortfall the person names in their own words carries no mark and follows the rules of an unmarked round. In a round answered `Revise this task` it is part of the change request (item 6).
2. **The popup:** one per round, with the label line `[4B] Review → Deliver · Q` (recorder.md "Popup label") and the layout of SKILL.md "Question rules".
   - In order: a short question; one `- ` line for each `[plan]` finding sent back, naming what it contains (severity, location, text); when a SHOULD-FIX is listed, a plain `- ` line that it is a problem worth fixing that does not block the gate; one `- ` line per choice saying what it leads to; `- Next:` last.
   - It is a popup of its own, with exactly three choices: `Adjust within approved scope` / `Revise this task` / `Fix within current plan` (list the recommended one first, with `(Recommended)`).
   - Record it with `ask gate=Q … rec="<recommended>"` and `answer gate=Q choice="<choice>"` (`by=L1` when L1 answers).
3. **Recommendation:**
   - `Revise this task` when the approach or the set of work units must change, or when the approved request does not stand (the fix changes the purpose, completion criteria, non-goals, constraints or exception cases).
   - Otherwise `Adjust within approved scope`: the approved request stands, and the planned units can make the fix once one more target file, behavior or dependency is allowed.
   - `Fix within current plan` is never recommended and is always listed last.
   - With several marked findings, the largest need decides.
4. **Scope of the answer:** it covers the whole round, its unmarked findings included (on `Revise this task` they go to the new plan too).
5. **`Adjust within approved scope`:** do "Adjust within approved scope" above: the `Scope change:` line under the approval and its `fix what="Scope change: …" files=plan.md` line. The approval is kept.
   - Then handle the round as `accept.md` does (item 3: small fix or "Back to Execute"; item 7: light path or "Back to Execute").
   - Pass the `Scope change:` line to every worker of the round. The line names the unit and each added file. L1 adds those files to the files to change in each later rerun call of that unit, naming the `Scope change:` line as their source.
6. **`Revise this task`:** do "Revise this task" above, items 1–7. By its item 2, go to ② Plan when only the method changes, and to ① Define when the purpose, completion criteria, non-goals, constraints or exception cases change. Pass every gate again from that phase. No `back-execute.py`.
   - At the architect call (`phases/plan.md` step 2A item 2), pass as the change request: the path `archive/<time>-rev<new rev>/review.md` (the round's findings, the unmarked ones included); the locations (severity and `path:line`, no explanation) of the findings the round sends back (all open items for `Rework: fix all open items`); and the shortfalls the person named in their own words in that G3 `Rework` round, as written.
   - Write `plan finding`, the sent-back locations and those shortfalls, as written, into the `<what changed>` part of the `## Revisions` line (Revise item 4). architect carries that section over, so they survive compaction or `continue`, also across ① Define.
7. **`Fix within current plan`:** handle the round as a round without a `[plan]` finding: the small fix (item 3), the light path (item 7) or "Back to Execute", each under its own conditions.
8. **Delegated approval:** when it is on, L1 answers with the recommended choice, `Revise this task` included. When it is off, the settled-popup rule (SKILL.md "Question rules") applies.
   - Whatever the answer, the round counts as one round of the loop it came from: after Review, the Review BLOCKER loop; at a G3 where L1 answered `Rework: fix all open items`, the G3 fix loop (gates.md "Delegated approval details").
   - `Revise this task` restarts neither count, and there is no new cap.
9. **The same finding comes back:** when a `[plan]` finding with the same severity and location returns in a later Review after `Fix within current plan` or `Adjust within approved scope`, the popup is asked again. The earlier answer did not clear it, so this one is not settled: the person is asked unless delegated approval is on (then the loop caps and E end the repetition). When the earlier choice could not add the unit or the approach the fix needs, recommend `Revise this task`.
10. **Other answers:** an answer typed in the Other field, or a question back, follows SKILL.md "Question rules".
11. **4th revision:** the popup before a 4th revision (Revise item 7) still applies.

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
2. Make sure `.claude/worktrees/` is excluded (the `git check-ignore` / `info/exclude` step of `build.md` step 3A item 2).
3. Run `git worktree add -b my-agent-task/<task-id> <task location>/.claude/worktrees/task-<task-id>` as one command (absolute path).
4. Tell the person to open a new session in that folder and send the request again.
5. Create nothing else: no `.active`, task folder or run-log line, so the two-question popup (`qn=1`/`qn=2`) is not recorded here.
