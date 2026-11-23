# ④ Accept: 7 Verify · 8 Review → G3

Verify and Review are never skipped, in any profile.

## 7. Verify

1. Record: `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" step n=7 name=Verify --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"`
   - This step line opens the phase, so the script writes the `cost` line of the moment itself (recorder.md `cost` row).
   - Before the verifier call, compare `git status --porcelain` with the changed files the coder reports listed plus the `fix` lines of L1. Show unexpected paths in the chat and in the "Open risks" row of the next overview; no extra popup.
2. Write the changed-file map: `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/changed-files.py" --task "<absolute task folder>"`; on a rerun after FAIL add `--previous "<absolute path of the latest archive/<ts>-run<N>/changed-files.md>"` when that file exists. It writes `changed-files.md` (each changed file with its work units, criteria and fingerprint, and the `Re-judge:` line) and prints one line. On a non-zero exit, state that line in the chat and go on without the map; the verifier then judges every criterion.
3. Hand it to `my-agent:verifier`. Pass: the file with the completion criteria (`scope.md` if it exists, otherwise `plan.md` for a small task), the `Scope change:` lines under `## Approval`, the deliverable path, the `changed-files.md` path, on a rerun the previous `verify.md` path (the latest `archive/<ts>-run<N>/verify.md`), and the result path `verify.md`. Do not pass the workers' explanations.
   - The verifier alone runs the tests and check commands, each once per run, and lists them under `## Commands run`; on a rerun it re-judges the failed criteria and those on the `Re-judge:` line and carries the rest (item 4 format).
   - For each `[check: person]` criterion the person reported on, first write `Scope change: criterion <n> checked by the person: <what they reported>` under `plan.md` `## Approval` with the changes.md "Adjust within approved scope" record (`fix what="Scope change: …" files=plan.md`). A `[check: person]` criterion with neither this line nor a `Scope change: criterion <n> is checked by the user later` line is FAIL.
4. `verify.md` format: first line `Verdict: ALL PASS` or `Verdict: FAIL`, then one line per criterion, `- <n>. PASS|FAIL <evidence>` (on a rerun, a carried criterion is `- <n>. PASS (carried from Run <m>) <evidence>`, read as PASS).
5. On FAIL, do "Back to Execute" below and go to Execute in ③ Build with the list of failed criteria. After the second FAIL on the same criterion, the new coder call asks for a structural argument (why no other failing form remains) before the fix, or L1 offers `Change scope` (E). On 3 FAILs in a row, go to E (gates.md "E escalation"). The count in a row is the number of `Verdict: FAIL` since the last `Verdict: ALL PASS` (or Revise this task). Count the `result=` of verifier `stop:` lines in the run-log from the end. `Run:` is only the judgment round, so it goes up after a PASS too.

## Back to Execute

Do this every time you go back to ③ Build for Verify FAIL, Review BLOCKER (when it is not a small fix), or G3 `Rework`. The next judgment overwrites `verify.md`·`review.md`; keep the current one first.

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/archive.py" --task "<absolute task folder>" --name run<Run: value of verify.md> --only verify.md review.md changed-files.md`. It copies those that exist to `archive/<time>-run<N>/`, compares the copies and prints that folder. On a non-zero exit, stop and report its line.
2. In `plan.md`, set `Status:` to `pending` for the work units tied to the failed criteria (or the shortfalls named at G3). If there is a last writer unit that combines a document deliverable, set it to `pending` too when any earlier unit becomes `pending`. Leave the rest as `done`. Hand the units set back to `pending` out again each as a new worker call, never a resume of the earlier worker, passing the archive folder paths from item 1 and the failed criterion numbers (`build.md` step 5 item 3).
3. Change `phase:` in `.active` to `3` and read `build.md`. Add the reason and the archive folder to the Execute step line: `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" step n=5 name=Execute back="<Verify FAIL criterion numbers / Review BLOCKER / G3 Rework: the shortfalls named, with criterion numbers>" archive=<archive folder> --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"` (instead of `build.md` step 5 item 1). In an Execute reached this way, skip `build.md` step 5 item 2 (base point, uncommitted-changes popup), and run coder in sequence in the main tree without a worktree.

## 8. Review → Deliver

In the dev profile, "G3 in the dev profile" in `profiles/dev.md` replaces items 4–6.

1. Record: `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" step n=8 name=Review-Deliver --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"`
2. Hand it to `my-agent:reviewer`. Pass: the deliverable path, the `plan.md` path, the `verify.md` and `changed-files.md` paths, the previous `review.md` path, if any (the latest `archive/<ts>-run<N>/review.md`), and the result path `review.md`. The first line of the result is `BLOCKER <count>`. The reviewer cites the verifier's `## Commands run` instead of running the suites again. Then run the findings command (gates.md "Gate reports"); on `findings: FAIL` (no `review.md`, or one older than this call) call a new reviewer once.
3. With 1 BLOCKER or more: if it is a small fix (the L1 exception in the SKILL.md level table), L1 fixes it (`fix` line), archives ("Back to Execute" item 1) and gets a new judgment. When only Review is redone, without Verify, do both: pass the reviewer the list of files L1 fixed (it runs the tests that cover them), and add a `## Applied after review` section at the end of the new `review.md` with Edit, listing each fix on its own line as `- <what was fixed> (<file>)` (without it, the hook blocks the G3 save and asks before the commit: `verify.md` is older than the change). If it is not a small fix, do "Back to Execute".
4. **G3 report (chat):** order: the Korean copy (gates.md "Gate reports"; Korean requests only), the `cost` line, the `ask` line, open the Report tab (`open-html.py --report … --pointer`; gates.md "Gate reports"), this report, then the popup and the `answer` line; the `cost` and `ask` bullets are in item 5. The report: `### Overview`, `### Takeaway` (Scope, Delivered, Next; cost (reference) may be named there), the overview table with the `Save path` row (**the exact path it will be saved to**), the findings table (gates.md "Gate reports") and the pointer line; failures and unhandled items go in the risks row. No Details section. The popup follows gates.md's popup text.
   - List the `[check: person]` criteria whose `Scope change:` line says `checked by the user later`, so the person decides on them at G3.
   - Save location: the deliverable location in `scope.md`. If none, `deliverable/` in the task folder.
   - File names are lowercase English with hyphens. If the same name exists, do not overwrite; add `-2`.
   - If the path is outside `~/dev`, state in the popup question that picking `Accept` counts as approval of that write.
5. **G3 popup:** to the person; while delegated approval is on, L1 answers per gates.md "Delegated approval details".
   - Run, right before the G3 popup, `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" cost --data-dir "<data folder>" --task-dir "<task_dir>"` (the order is in item 4).
   - The popup body lists the open SHOULD-FIX and NITPICK items of `review.md`.
   - `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" ask gate=G3 q="Final acceptance: <task-id> → <save path>" rec="<recommended choice>" --data-dir "<data folder>" --task-dir "<task_dir>"`
   - Popup: `Accept (Recommended)` / `Rework` / `Abort`; with open items, gates.md "Gate reports", "G3 with open review items".
   - `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" answer gate=G3 choice="<chosen choice>" --data-dir "<data folder>" --task-dir "<task_dir>"`
6. **Accept:**
   - Do gates.md "Check before anything leaves" on the final version.
   - Copy the final version from the task folder to the save location. Workers do not write outside the task folder, so L1 makes this copy. If the judgments are not fresh, the hook (`verdict-fresh-check.py`) blocks it. If blocked, redo from Verify.
   - Add `Delivered: <path>` to `intake.md` and run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" deliver path=<path> --data-dir "<data folder>" --task-dir "<task_dir>"`.
   - Do "Blueprint update" below. In a git location its files stay uncommitted; say so in one line.
   - Change `intake.md` to `Status: done`.
   - If delegated approval is on, run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" delegate state=off how=end --data-dir "<data folder>" --task-dir "<task_dir>"` before the retrospective.
   - Retrospective: read `retro.md` and do its "Retrospective". After the retrospective ends, run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/cd-guard.py" --remove --location "<task location>" --task "<absolute task folder>"` and show its line; last of all delete `.active` and this task's line in `<data folder>/active-index.json` (the retrospective needs `.active`).
7. **Rework:** If the criteria stay the same, do "Back to Execute" and go to ③ Build with the shortfalls as failed criteria. Small scope adjustments the person asks for after the G3 report are collected into one `Scope change:` round and re-judged once (one Execute, one Verify, one Review). If the request changes the criteria, take changes.md "In-flight revision".
8. **Abort:** the "Abort" procedure in changes.md.

## Blueprint update

The project blueprint is `docs/blueprint/` in the task location (`features.md`, `decisions.md`, `backlog.md`). Update it once per task, in every profile, after the G3 `Accept` (dev: `Commit`) answer, at the point item 6 (dev: "G3 in the dev profile" item 4) gives.

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/blueprint.py" check --loc "<task location>" --data-dir "<data folder>"`. If the first line is `blueprint: off …` (the task location is the data folder), skip this section. `problem:` lines here are older than this task; pass them on in item 2.
2. Hand it to `my-agent:writer`, with no `Work unit:` line. Pass: the job name `Blueprint update`, the path `${CLAUDE_PLUGIN_ROOT}/l3-workers/blueprint-format.md`, the folder of the `blueprint:` line, the task ID, the date of the G3 `answer` line, the task folder files (`intake.md`, `explore.md`, `scope.md` if any, `plan.md`, `plan-review.md`, `verify.md`, `review.md`, `changed-files.md`) and where the deliverable is (the save path; dev: the changed files). Do not pass explanations. Model and effort: recorder.md "Model and effort per call".
3. Run the item 1 command again. On `problem:` lines or a `PARTIAL` report, hand them to a new writer call once. If they remain, show them in the chat and go on: a blueprint problem never undoes the Accept or Commit.
4. Show in the chat the `ok:` line and the per-file lines of the writer's report, and the lines `git diff -U0 -- docs/blueprint/` shows as deleted (none: say so).
