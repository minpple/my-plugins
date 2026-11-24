# Dev profile (dev)

Tasks that change code in a git repository (feature, bug fix, refactoring). The deliverable is one commit approved at G3. On the normal path the person is asked 3 times: G1a, G1b, G3; for a small task, 2 times: G1b, G3 (not counting questions asked only the first time, such as the task location and `.gitignore`, or the G2 permission dialog).

## Rules per phase

| Step | Dev profile |
|---|---|
| 2 Explore → Scope | Always hand it to explorer: related files and their callers, current behavior, check commands (test·lint·build) and whether each runs here (`define.md` "Environment"), uncommitted changes. The Scope interview opens with one scope-width popup (`ask gate=Q … rec="Only what was asked"`/`answer gate=Q` lines): `Only what was asked (Recommended)` / `Related things too` / `The richer result` (more of the purpose: related items in the same task, plus documents, screens and tests around them). Every later scope or design popup offers the richer option second, and first with `(Recommended)` after `The richer result`. It settles seven things in `scope.md`: **purpose and users** (written in `scope.md` `## Purpose and users` as a `Background:` paragraph, then a `Purpose:` paragraph, then the users line), **completion criteria** (numbered `1.`, `2.`; each ends with one check tag: `[check: command]`, `[check: file]`, `[check: URL]` or `[check: person]`), **hard constraints** (what must not change, compatibility, performance), **exception cases** (empty input, errors, boundary values), **data** (input/output formats, storage), **non-goals**, **UX preferences** (messages, screens, CLI output). `scope.md` holds only WHAT/WHY. Do not write file or function names. Then Scope Review (`define.md` "Scope Review"), and confirm with G1a. |
| Small task exception | If `explore.md` shows fewer than 3 files to change, and the request already answers purpose and users, completion criteria and non-goals: skip the Scope interview, Scope Review and G1a. L1 passes a 5-line summary (purpose, numbered completion criteria, non-goals, constraints, exception cases) to architect, which puts it at the top of `plan.md` as `## Scope summary` and `## Completion criteria`. Skip Plan Review and write `SKIPPED small task` in `plan-review.md`. State the decision and its reason in one line, on the line after the Intake report. There is no Background research for a small task (a web fact that changes the plan means it is not small). |
| 3 Plan | A work unit (`### u<n>`) is one piece of code (`my-agent:coder`). Per unit: files to change, tests to add (each tagged with the criterion or exception case it covers; plan-reviewer judges the coverage), completion criterion numbers, check commands. Only units that change different files go in the same parallel group. The mock-up is a sample of the behavior after the change (command output, response, screen). |
| 4 Plan Review | Not skipped (except for a small task). Findings are handled as in `plan.md` step 4; the decisions go in `## Decisions` of `plan-review.md`. |
| G1b | Plan approval. Show `scope.md` (for a small task, the 5-line summary) with it. |
| 5 Execute | At the start, record the base point (`base commit=<HEAD> dirty=<summary>`). If the main tree has uncommitted changes (derived files do not count), popup: `User cleans up first (Recommended)` / `Proceed as is` / `Abort`. For `Proceed as is`, use no worktree and run every work unit in sequence in the main tree. Otherwise, call only the coders of the first parallel group with the call argument `isolation: "worktree"`, and call later groups in sequence in the main tree. Worktree-isolated session (`--git-dir` ≠ `--git-common-dir`): `build.md` step 5 item 2. |
| 6 Merge | Move worktree results into the main tree in the plan's work unit order. coder does not commit, so a worktree's changes are an uncommitted diff and new files: copy the new files from `git -C <worktree> ls-files --others --exclude-standard` first, then write the diff with `git -C <worktree> diff --binary HEAD --output=<task folder>/work/<unit>.patch` and move it with `git apply <that file>`, then compare each moved file with its worktree copy (`cmp`, one call each); all equal: read its branch (`git -C <worktree> branch --show-current`), `git worktree remove --force <worktree>`, `git branch -D <branch>`; when that removal is refused, for any reason (a lock from a background process the coder left is one), make one attempt only per worktree, then keep that worktree and its branch (no `git branch -D`), name the path of each kept worktree in one chat line and in the "Open risks" row of G3. Ask no popup and go on with the next worktree and the rest of 6 Merge. Each worktree is handled on its own: the others are removed as usual. For a refused removal, do not unlock the worktree (no `git worktree unlock`) and do not kill any process. Compare result, a difference: keep the worktree and name the files in one chat line and in the "Open risks" row of G3, no popup. When `git -C <worktree>` is refused, copy the files the coder report lists with `cp -p` (absolute paths) and compare with `cmp`. For conflicts, see `build.md` item 6. After moving everything, do "Upstream check" below, then run the check commands (tests, lint) from `explore.md`. If they fail, hand the unit back to its coder in the main tree along with the failing tests. |
| 7 Verify | verifier judges each criterion from the changed-file map (`accept.md` step 7) and the `git diff` of its files, `git status --porcelain`, new files and check command results; it alone runs the tests and check commands, once each per run, and a rerun re-judges only the failed and touched criteria. The second line of `verify.md`, `Run:`, is the round. On 3 FAILs in a row, E. |
| 8 Review → G3 | reviewer looks at the code review and the definition of done (`review.md`), citing the test results in `verify.md` instead of running the suites again. G3 is commit approval ("G3 in the dev profile" below): show the diff stat and the proposed commit message as table rows (the Report tab shows Verify and Review), then popup `Commit (Recommended)` / `Rework` / `Abort` (with open review items: gates.md "Gate reports"). The commit message lists the completion criterion numbers. |

## G3 in the dev profile (commit approval)

The deliverable is a commit, so do this instead of `accept.md` step 8 items 4–6.

G3 goes to the person; while delegated approval is on, L1 answers per gates.md "Delegated approval details".

1. **Chat report** (shown at the point item 3 gives; gates.md "Gate reports"): `### Overview`, `### Takeaway` (Scope, Delivered, Next; cost (reference) may be named there; the judgment summary goes here: `verify.md` `Run:`), the overview table with a `Commit message` row (the proposed message: first line says what changed, then `criteria: 1, 2, 3`) and a `Diff` row (`<N> files, +<a>/-<b>` from the last line of `git diff --stat`), the findings table (gates.md "Gate reports") and the pointer line. The risks row holds unexpected paths and the `[check: person]` criteria whose `Scope change:` line says `checked by the user later`, so the person decides on them at G3. No Details section: the diff hunks and the list of new files are not printed. The popup follows gates.md's popup text.
2. Compare `git status --porcelain` with the changed files the coder reports listed plus the `fix` lines of L1; show unexpected paths in the chat and in the "Open risks" row (no extra popup). Commit only the files this task changed (changes since the `base` line, excluding `<task_dir>/`; if `<task_dir>/.gitignore` is `# my-agent: commit`, include the task folder too) and the blueprint files of item 4.
3. Record before and after the popup. Run, right before the G3 popup, `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" cost --data-dir "<data folder>" --task-dir "<task_dir>"`. Order: the Korean copy (gates.md "Gate reports"; Korean requests only), the `cost` line, the `ask` line, open the Report tab (`open-html.py --report … --pointer`; gates.md "Gate reports"), the chat report of item 1 with the pointer line it printed, the popup, the `answer` line.
   - `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" ask gate=G3 q="Commit approval: <task-id>" rec="<recommended choice>" --data-dir "<data folder>" --task-dir "<task_dir>"`
   - Popup: `Commit (Recommended)` / `Rework` / `Abort`; with open review items the choices and the recommended one follow gates.md "Gate reports". The body lists the open SHOULD-FIX and NITPICK items of `review.md` and says what happens next: the blueprint update (`docs/blueprint/`), one commit on the current branch with the shown message, then the retrospective.
   - Remote take: read retro.md "Remote update" before this popup; when it offers one, it is the second choice, after `Commit`, and the question names it.
   - `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" answer gate=G3 choice="<chosen choice>" --data-dir "<data folder>" --task-dir "<task_dir>"`
4. **Commit:**
   - Do accept.md "Blueprint update" first; the blueprint files it changed join this commit.
   - Do gates.md "Check before anything leaves" on the files to commit.
   - `git add <files>`, then `git commit -m "<message>"`. The G2 permission dialog showing once more is a deliberate second check. If the judgments are not fresh, the hook (`verdict-fresh-check.py`) asks (the G2 dialog) and names the stale judgment; do not allow it for the task's commit, redo from Verify. Never use `--no-verify`.
   - Add `Delivered: commit:<short sha>` to `intake.md` and run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" deliver path=commit:<short sha> --data-dir "<data folder>" --task-dir "<task_dir>"`.
   - Change `intake.md` to `Status: done`. On a remote take do retro.md "Remote update" now. If delegated approval is on, run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" delegate state=off how=end --data-dir "<data folder>" --task-dir "<task_dir>"`. Read `retro.md` and do its "Retrospective", then run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/cd-guard.py" --remove --location "<task location>" --task "<absolute task folder>"` and show its line, and last of all delete `.active` and this task's line in `<data folder>/active-index.json`.
5. **Rework** and **Abort** are the same as `accept.md` step 8 items 7 and 8. On abort, do not revert the changed files; only report their list.

## Upstream check (6 Merge)

Every time 6 Merge runs, after the worktree results are moved and before the check commands.

1. The refs to compare: the current branch's upstream (`git rev-parse --abbrev-ref @{u}`) and, when the current branch is not the remote's default branch, that branch (`git symbolic-ref --short refs/remotes/origin/HEAD`). With no remote, or neither ref, skip this check.
2. `git fetch origin <branch>` for each ref (one call each; when it fails, say so in one chat line and skip the check), then `git rev-list --count HEAD..<ref>`. All 0: go on.
3. Otherwise ask one popup that names each ref and its count, with `ask gate=Q … rec="Bring them in now"`/`answer gate=Q` lines: `Bring them in now (Recommended)` / `Go on without them`.
4. Bring them in with `git merge --autostash <ref>`.
   - The merge itself conflicts (committed history against the ref): `git merge --abort`, then E: `I resolve it and say when done (Recommended)` / `Go on without them` / `Abort`.
   - Putting the task changes back conflicts: a conflict of `build.md` 6 Merge item 3 (small: L1; larger: a new coder call in the main tree, with the conflict and the notes file).
   - Record: `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" merge unit=upstream files="<n> commits from <ref>" how="<fast-forward / merge commit / conflicts resolved>" by=<L1 or coder> --data-dir "<data folder>" --task-dir "<task_dir>"`

## Agents used

Names are the names used to call them.

| Agent | Steps | Result |
|---|---|---|
| `my-agent:explorer` | 2 | report → L1 saves it to `explore.md` |
| `my-agent:scope-reviewer` | 2 (before G1a; not for a small task) | `scope-review.md` |
| `my-agent:architect` | 3, G1b revisions | `plan.md` |
| `my-agent:plan-reviewer` | 4 | `plan-review.md` |
| `my-agent:coder` | 5, 6 (failed tests, large conflicts) | code and tests (not committed) |
| `my-agent:writer` | prototype | `prototype/index.html` |
| `my-agent:verifier` | 7 | `verify.md` |
| `my-agent:reviewer` | 8 | `review.md` |
