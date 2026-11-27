# Unit copies: the coder units of a parallel group run in their own copies

L1 reads this file at the first parallel group with 2 or more pending coder units (`phases/build.md` step 3A item 3). A copy is a detached copy of the task location, one per coder unit, made by `worktree.py`, so the units of a group run at the same time and never write into each other's files. It works in a git location and in a folder that is not a repository.

With `<common>` = `--location "<task location>" --task "<absolute task folder>"`, the calls are:

- `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/worktree.py" create <common> --unit u<n> [--unit u<m> …]`
- `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/worktree.py" merge <common> --unit u<n>`
- `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/worktree.py" keep <common> --unit u<n>`
- `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/worktree.py" remove <common> --unit u<n>`
- `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/worktree.py" list <common>`
- `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/worktree.py" cleanup <common>`

Exit codes: 0 done, 1 not done (a git or file error), 2 bad arguments, 3 sequential, 4 `conflict`, 5 `differs`.

## When

- Every parallel group with 2 or more pending coder units, in every profile, also after "Back to Execute", and also a coder group run in a workflow (`build.md` "Workflow rules"). Never pass `isolation`. A session in a linked worktree gets copies like any other.
- Before creating, run `list`. A unit with a kept copy is left out: it reruns alone in the main tree, with no `Worktree:` line, after the group's other units are merged, and its kept copy stays. With fewer than 2 coder units left, the group runs as today.
- An inline coder role (`pass=inline`) gets no copies (SKILL.md "Inline role"): its units run one at a time in the main tree in this session, and no `create` runs for such a group, so no unit is `running` while L1 edits the main tree.

## Create

One `create` call for the group (`--unit` once per coder unit). It prints the cd-guard line, `worktree: <unit> <path>` per unit and `base: <sha>`.

- Exit 0: show the cd-guard line. Pass each coder `Worktree: <path>` as the prompt's second line, after `Work unit:`. Pass each check command with every task-location path replaced by the copy path; the check script runs in 3B Merge (`build.md`), in the main tree after the merge.
- Workflow: one `create` for all its coder units before the workflow starts, and each coder `agent()` prompt carries its `Worktree:` line the same way.
- Any other exit: show its line as one chat line and run that group's coder units one at a time in the main tree. This covers the size or file-count limit, no git, a nested repository, Windows, a refused session guard and a failed create. No popup, also under delegated approval.

## While units run

A stopped coder's retry uses the same `Worktree:` line. The group is merged only after each unit has finished or the person decided at E. When the E answer gives a unit up, run `keep` for it: its copy is kept and named in one chat line and in the G3 "Open risks" row.

## Merge

Run it in 3A right after the group finishes (for a workflow, after it returns and its result checks pass), before the next group is handed out, so the next group's copies hold its result. 3B Merge item 3 points here for anything left. Run `merge` per unit in plan order and record each with the run-log `merge` line (`build.md` 3B Merge item 3). Show the `merged` line, then by result:

- Exit 0 with `kept:` (git refused the removal), and exit 5 (`differs`, files named): the patch is applied and the copy is kept. One chat line and the G3 "Open risks" row; no popup, no rerun.
- An `ignored:` line: one chat line saying those files were not merged (generated or local files).
- Exit 4 (`conflict`): nothing was applied and the copy is kept. Handle it by the three bullets of `build.md` 3B Merge item 3. After L1 resolves a small conflict, or after a main-tree rerun of the unit succeeds, run `remove` and say so in one chat line. While an E answer is pending, the copy is kept.
- Exit 1: show its line. The copy is kept and named in one chat line and the G3 "Open risks" row. The unit reruns alone in the main tree after the group's other merges, as a new worker call with the cause passed (build.md 3A item 3 rerun route). No popup, no E.
- Exit 2: nothing changed. Correct the command and run `merge` again; no rerun.

Then the reruns, one at a time, each without a `Worktree:` line and with the notes file path. Then the check script runs in 3B Merge (`build.md`), in the main tree.

## Leftover copies and cleanup

- Run `list` on resume and on Abort. Resume handles each copy by its state. A `(running)` copy gets the `Merge` / `Redo` / `Discard` popup (`Merge` is "Merge" above for that unit; `Redo` and `Discard` run `remove`, and `Redo` hands the unit out again). A `(kept)` copy gets one chat line, no popup and no `Merge`, because it may already be applied or wait for its unit's rerun; it stays as it is.
- When delegation stops for "Revise this task", or an E answer ends a group before its merge, the group's copies are not merged and stay `(running)`. On a revision, L1 passes the `(running)` copies to architect as unmerged coder worktrees among the deliverables already made. After the revised plan is approved, and before the sweep, L1 applies each approved `## Existing work` row that names a `(running)` copy: merge runs `merge` for that unit (its result follows "Merge" above); redo and discard run `remove`, with one chat line. Redo then hands the unit out again.
- The sweep runs once before a group's coder units are first handed out, never before a retry, when the task folder has `unit-copies.json`. It runs `list`, then `keep` for each `(running)` copy listed, which is stale (only copies with no row are left, even one whose unit is in the group), and names them in one chat line. Such a unit then runs as a kept-copy unit.
- `cleanup` replaces the `cd-guard.py --remove` command on every path that ends the task, because it runs that removal itself. It keeps the store while a copy is left and names both paths; a second `cleanup`, after `Clean up worktrees` removed the copies, finishes the removal.
- Kept copies and the store path are named in one chat line and the G3 "Open risks" row.
