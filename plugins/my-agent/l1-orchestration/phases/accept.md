# ④ Accept: 4A Verify · 4B Review → G3

Verify and Review are never skipped, in any profile.

## 4A Verify

1. Before the judges, in this order:
   - Compare `git status --porcelain` with the changed files the coder reports listed plus the `fix` lines of L1. Show unexpected paths in the chat and the next "Open risks" row; no popup.
   - Write the changed-file map: `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/changed-files.py" --task "<absolute task folder>"`. On every rerun after Back to Execute (Verify FAIL, Review BLOCKER, G3 `Rework`) add, each only when the file exists, `--previous "<absolute path of the latest archive/<ts>-run<N>/changed-files.md>"` and `--review "<the same folder's review.md>"`. After a G3 `Rework` also add one `--rework-criterion "<n>: <shortfall>"` per named criterion and one `--rework-finding "<path>:<line>"` per picked SHOULD-FIX line, from the `back=` of the latest Execute step line. It writes `changed-files.md` (each changed file with work units, criteria and fingerprint, then the `Re-judge:` and `Checks:` lines) and prints two lines: the map line and `checks: <status>`. On exit 2 with a line naming a rework criterion or location, correct it and run again. On any other non-zero exit, state that line in the chat and go on without the map; the verifier then judges every criterion.
   - Show the `checks:` line as one chat line. On `stale`, on `docs-only (run due; …)`, or on `missing` when this round's 3B did not run the script (a resume or a skipped 3B; never after this round's run failed or was stopped), run the check script once more with all its commands (`build.md` 3B item 5; it narrows itself on `docs-only (run due`), say so in one chat line (the test files the status line names, any `tree changed by the run:` line), then run `changed-files.py` again with the same arguments. `docs-only (checked; …)` and `current` get no rerun. Go on whatever it says: no second rerun, also when a command fails again. `no fingerprint` gets no rerun; the verifier runs the commands itself.
2. Record both step lines, 4A and then 4B before the judges start; sequential: the 4B line comes after the verifier ends. 4A line: `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" step n=4A name=Verify --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"`
   - This step line opens the phase; the script writes the `cost` line of the moment itself.
3. Hand it to `my-agent:verifier`. Pass: the file with the completion criteria (`scope.md` if it exists, otherwise `plan.md` for a small task), the `Scope change:` lines under `## Approval`, the deliverable path, the `changed-files.md` path, `checks.md` when it exists, on a rerun the previous `verify.md` path (the latest archived one), and the result path `verify.md`. Do not pass the workers' explanations.
   - Start `my-agent:reviewer` in the same message (4B item 2): the two judges work together. With no `checks.md` and check commands that exist, go one after the other: the verifier first, then the reviewer with `verify.md`. With no check commands, both still start together. The host file says whether started judges overlap.
   - The verifier reuses a current record, else runs the tests and check commands itself, each once per run, listed under `## Commands run`; on a rerun it re-judges the failed criteria and those on the `Re-judge:` line and carries the rest (item 4 format).
   - A judge that stops or leaves no usable result file is called again alone; combine the results when both are present.
   - For each `[check: person]` criterion the person reported on, first write `Scope change: criterion <n> checked by the person: <what they reported>` under `plan.md` `## Approval` with the changes.md "Adjust within approved scope" record (`fix what="Scope change: …" files=plan.md`). A `[check: person]` criterion with neither this line nor a `Scope change: criterion <n> is checked by the user later` line is FAIL.
4. `verify.md` format: first line `Verdict: ALL PASS` or `Verdict: FAIL`, then one line per criterion, `- <n>. PASS|FAIL <evidence>` (on a rerun, a carried criterion is `- <n>. PASS (carried from Run <m>) <evidence>`, read as PASS).
5. Combine the two results:

   | Verify | Review | Next |
   |---|---|---|
   | ALL PASS | BLOCKER 0 | G3 |
   | ALL PASS | BLOCKERs that fit the small fix | 4B item 3 (small fix) |
   | ALL PASS | a larger BLOCKER | Back to Execute |
   | FAIL | any | Back to Execute: the coders fix the failed criteria and the review's BLOCKER lines only; SHOULD-FIX and NITPICK stay for the person at G3 |

   A `[plan]` BLOCKER first takes changes.md "Plan findings (Review)". The archived `review.md` feeds the next round (`changed-files.py --review`).
6. On FAIL, do "Back to Execute" below and go to Execute in ③ Build with the list of failed criteria and the review's BLOCKER locations. After a criterion's second FAIL, the new coder call asks for a structural argument (why no other failing form remains) before the fix, or L1 offers `Change scope` (E). On 3 FAILs in a row, go to E (gates.md "E escalation").

## Back to Execute

Do this each time you go back to ③ Build for Verify FAIL, Review BLOCKER (not a small fix), or G3 `Rework`. The next judgment overwrites `verify.md`·`review.md`; keep the current one first.

1. Name the work units tied to the failed criteria and the review's BLOCKER locations (or the G3 shortfalls) and run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/back-execute.py" --task "<absolute task folder>" --units <u2 u3 …> --back "<Verify FAIL criterion numbers / Review BLOCKER / G3 Rework: the shortfalls named, with criterion numbers, and the picked SHOULD-FIX locations>" --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"`. It archives the judgments, sets those units to `pending` (also a last writer unit that combines a document deliverable, when an earlier unit becomes `pending`), sets `phase:` in `.active` to `3` and writes the Execute step line with `back=` and `archive=`. On a non-zero exit, stop and report its line.
2. Read `build.md`. Hand the units set back to `pending` out again, each as a new worker call, never a resume of the earlier worker, passing the archive folder path from item 1 and the failed criterion numbers (`build.md` step 3A item 3). Skip `build.md` step 3A items 1 and 2 (the step line is written; base point, uncommitted-changes popup); coder copies follow `build.md` step 3A item 3.

## 4B Review → Deliver

In the dev profile, "G3 in the dev profile" in `profiles/dev.md` replaces items 4–6.

A round that sends back a `[plan]` finding first takes changes.md "Plan findings (Review)"; no fix starts before its answer.

1. Record (in 4A item 2, right after the 4A line): `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" step n=4B name=Review-Deliver --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"`
2. Hand it to `my-agent:reviewer`, in the message that starts the verifier (4A item 3). Pass: the deliverable path, the completion-criteria file (as in 4A item 3), the `plan.md` path, `checks.md` when it exists, the `changed-files.md` path, the previous `review.md` path, if any (the latest archived `review.md`), and the result path `review.md`. Pass `verify.md` only in the sequential case (no `checks.md`). The result's first line is `BLOCKER <count>`. The reviewer cites `checks.md` (sequential: the `## Commands run` of `verify.md`) instead of running the suites again. Then, before the writer call, run the read-only check `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/findings.py" --task "<absolute task folder>" --file review`; on `findings: FAIL` (no `review.md`, or one older than this call) call a new reviewer once.
3. With 1 BLOCKER or more and Verify ALL PASS (4A item 5): if it is a small fix (the L1 exception in the SKILL.md level table), L1 fixes it (`fix` line), archives it with `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/archive.py" --task "<absolute task folder>" --name run<Run: value of verify.md> --only verify.md review.md changed-files.md` (on a non-zero exit, stop and report its line) and gets a new judgment.
   - **Documents-only small fix** (every file L1 changed is a document: a `docs` folder segment, no `tests` one): L1 runs the check script, then `changed-files.py` with `--previous` and `--review` (archived) and, after a Rework, its Rework arguments. A fixed file with criterion numbers in the map: record the 4A and 4B step lines and start the verifier (light judgment) and the reviewer together; otherwise only Review (pass it the list of files L1 fixed), with `## Applied after review` as below. A failing narrowed command takes "Back to Execute" with the failing test.
   - Any other small fix: a new judgment with both judges starts at 4A item 1: the fix makes the record stale, so the check script runs again first. When only Review is redone, without Verify, do both: the check script does not run again; pass the reviewer the list of files L1 fixed (it runs the tests that cover them, and cites `checks.md` for the rest), and add a `## Applied after review` section at the end of the new `review.md` with Edit, listing each fix on its own line as `- <what was fixed> (<file>)` (else the hook blocks the G3 save and asks before the commit). If it is not a small fix, do "Back to Execute".
4. **G3 report (chat):** Order: the Korean copy (gates.md "Gate reports"; Korean requests only), the writer call (`Gate report: G3`), `pre-gate.py` (item 5), this report, the popup, the `answer` line. The report: `### Overview`, `### Takeaway` (Scope, Delivered, Next; L1 adds only the cost (reference), as a short table after the printed output, before the popup; nothing else for general and research), the overview table with the `Save path` row (**the exact path it will be saved to**, as the writer writes it), the findings table (gates.md "Gate reports") and the pointer line. The popup follows gates.md.
   - List the `[check: person]` criteria whose `Scope change:` line says `checked by the user later`, for the person to decide at G3.
   - Save location: the deliverable location in `scope.md`, else `deliverable/` in the task folder.
   - File names: lowercase English with hyphens. Never overwrite a same name; add `-2`.
   - If the path is outside `~/dev`, say in the popup question that `Accept` approves that write.
5. **G3 popup:** to the person; while delegated approval is on, L1 answers per gates.md "Delegated approval details".
   - Run, right before the G3 popup, `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/pre-gate.py" --gate G3 --task "<absolute task folder>" q="Final acceptance: <task-id> → <save path>" rec="<recommended choice>" --report-text "<absolute task folder>/report/G3.md" --data-dir "<data folder>" --task-dir "<task_dir>"` (it writes the `cost` and `ask` lines).
   - The popup body lists the open SHOULD-FIX and NITPICK items of `review.md`.
   - Popup: `Accept (Recommended)` / `Rework` / `Abort`; with open items, gates.md "Gate reports", "G3 with open review items".
   - `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" answer gate=G3 choice="<chosen choice>" --data-dir "<data folder>" --task-dir "<task_dir>"`
6. **Accept:**
   - Do gates.md "Check before anything leaves" on the final version. Copy the final version from the task folder to the save location. If the judgments are not fresh, the hook (`verdict-fresh-check.py`) blocks it. If blocked, redo from Verify.
   - Add `Delivered: <path>` to `intake.md` and run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" deliver path=<path> --data-dir "<data folder>" --task-dir "<task_dir>"`.
   - Do "Blueprint update" below. In a git location its files stay uncommitted; say so in one line.
   - Change `intake.md` to `Status: done`.
   - If delegated approval is on, run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" delegate state=off how=end --data-dir "<data folder>" --task-dir "<task_dir>"` before the retrospective.
   - Retrospective: read `retro.md` and do its "Retrospective". After it ends, run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/worktree.py" cleanup --location "<task location>" --task "<absolute task folder>"` and show its lines; last of all delete `.active` and this task's line in `<data folder>/active-index.json` (the retrospective needs `.active`).
7. **Rework:** The picked SHOULD-FIX lines are the open ones the person names, or all open ones for `Rework: fix all open items`. Take the light path in two cases. When every picked item (SHOULD-FIX or NITPICK) is fixed by a documents-only small fix: item 3's route; it wins whenever every changed file is a document. When every picked item is a NITPICK and the fix is a small fix that touches code: L1 fixes them (`fix` line), archives with `archive.py` and gets only Review again with the list of files L1 fixed, then adds `## Applied after review`, as in item 3; Back to Execute and Verify are skipped, and the check script does not run again. The round counts as one G3 Rework round. A picked SHOULD-FIX whose fix touches any other file, or a larger fix, takes "Back to Execute"; a new BLOCKER in the Review rerun takes item 3. If the criteria stay the same, do "Back to Execute" with the shortfalls as failed criteria.
8. **Abort:** the "Abort" procedure in changes.md.

## Blueprint update

The project blueprint is `docs/blueprint/` in the task location (`features.md`, `decisions.md`, `backlog.md`). Update it once per task, in every profile, after the G3 `Accept` (dev: `Commit`) answer, at the point item 6 (dev: "G3 in the dev profile" item 4) gives.

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/blueprint.py" check --loc "<task location>" --data-dir "<data folder>"`. On a first line `blueprint: off …` (the task location is the data folder), skip this section. Pass its `problem:` lines (older than this task) to item 2.
2. Hand it to `my-agent:writer`, with no `Work unit:` line. Pass: the job name `Blueprint update`, the path `${CLAUDE_PLUGIN_ROOT}/l3-workers/blueprint-format.md`, the folder of the `blueprint:` line, the task ID, the date of the G3 `answer` line, the task folder files (`intake.md`, `explore.md`, `scope.md` if any, `plan.md`, `plan-review.md`, `verify.md`, `review.md`, `changed-files.md`) and the deliverable (the save path; dev: the changed files). No explanations. Model and effort: recorder.md "Model and effort per call".
3. Run the item 1 command again. On `problem:` lines or a `PARTIAL` report, hand them to a new writer call once. If they remain, show them in the chat and go on: a blueprint problem never undoes the Accept or Commit.
4. Show in the chat the writer report's `ok:` line and per-file lines, and the lines `git diff -U0 -- docs/blueprint/` shows as deleted (none: say so).
