# ① Define: 1A Intake · 1B Explore → Scope → Background research

Step 1A Intake is the "Intake" procedure in new-task.md. This file starts at step 1B. For differences per profile, follow the profile file.

## 1B Explore → Scope

1. Record: `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" step n=1B name=Explore-Scope --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"`
2. **Explore:** If the request is about existing files or a project, hand it to `my-agent:explorer`.
   - Pass: the `intake.md` path and a list of what to find out (where the related files are, current behavior, constraints).
   - explorer writes no files; it returns a report (its last message), and L1 saves it as is to `explore.md`. If the first line is `PARTIAL`, follow recorder.md "Failure handling".
   - If the request alone is enough, do not delegate; write one line `Skipped: <reason>` in `explore.md`.
   - **Blueprint:** check with Glob whether `<task location>/docs/blueprint/` has a file (the project blueprint: `features.md`, `decisions.md`, `backlog.md`; accept.md "Blueprint update"). If it has, hand Explore to explorer in every profile, also where the request alone would be enough, and add the blueprint to the list of what to find out; its report then has a `## Blueprint` section. When the request goes against a `Constraint`, `Non-goal` or `Decision` line, ask one popup that names the line: `Keep it (Recommended)` / `Change it`, with `ask gate=Q … rec="Keep it"`/`answer gate=Q` lines before and after; on `Change it`, write the change into the scope (a criterion or a non-goal) so the plan and the blueprint follow it.
3. **Scope interview:** Settle WHAT/WHY. What to ask is in the profile file.
   - If the profile file has an exception that skips the interview and G1-A (the small-task exception of the dev and general profiles), judge it from the explore result and follow it as written.
   - Ask one question at a time in a popup. When free input is needed, offer the Other field along with the choices.
   - Open with the profile file's scope-width popup.
   - Scope questions follow SKILL.md "Question rules" (multi-select or the Other field when the single recommended answer is likely to be replaced).
   - For a task with a screen, ask once about screen behavior and look (filters, progress graphics, animation), or put them in the recommendation. This question has the choice `Prototype before G1-A`, which triggers a G1-A prototype. A G1-A `Revise` answer that asks for a prototype does the same.
   - **Environment:** for each `cannot run:` or `fail:` line under `## Check commands` in `explore.md`, ask one popup that names the command and the reason, with `ask gate=Q … rec="<recommended choice>"`/`answer gate=Q` lines. This also holds when the interview is skipped (the small task).
     - `cannot run:` → `I fix the environment first (Recommended)` / `Judge without this command`; the Other field takes a command to use instead. After the first, run the command once when the person says it is fixed; if it still cannot run, ask again.
     - `cannot run:` with nested project lines of which some run → `Run only the projects that run here (Recommended)` / `I fix the environment first` / `Judge without this command`. The first is written as `replaced by <the command limited to those projects, each one named>`.
     - `fail:` → `Failures from before this task do not count (Recommended)` / `Fix them in this task` (then a completion criterion).
     - Write each answer except a fix that worked as one line under `## Environment` in `scope.md` (small task: in the summary's constraints): `- Environment: <command> — not run here (<reason>) | replaced by <command> | fails before the task (<tests>)`. The verifier follows these lines.
   - **Background questions:** at the end of the interview L1 writes questions for the web only when all three hold: (1) the answer changes a plan choice (work unit split, library, file layout); (2) the project cannot answer it (location, blueprint, reference files; `explore.md` `## Unverified` is the clue); (3) it is not the content of the deliverable (that stays with researcher units after G1-B). Write at most 4. With more candidates, keep the 4 that change the plan most; pass the rest to the architect in the step 2A call as candidates that were not researched, and it writes each as `To confirm`. None in the research profile, for a small task, or on a host without web tools (profile file, `hosts.md`). The questions get no popup of their own: the person confirms them with the scope at G1-A (`Revise` removes or edits one). Under delegated approval L1 answers G1-A as it does today, which confirms them.
   - **G1-A prototype:** L1 adds `## Prototype` with the line `Prototype: requested` to `scope.md` with Edit (the plan-approved check then allows `my-agent:writer` to write the prototype). It hands `<task_dir>/<task-id>/prototype/index.html` to `my-agent:writer` with `scope.md` and the `mock-up` skill files (`${CLAUDE_PLUGIN_ROOT}/skills/mock-up/SKILL.md`, `templates/canvas.html` and the matching `references/*.md`, as plan.md "G1-B plan approval" item 2 lists them). L1 captures, checks and opens it as that item describes (`capture.sh`, `index.png`, `open-html.py`, the local path in the `Prototype` row), then shows G1-A. The G1-A popup keeps its three choices.
4. **Confirm the scope:**
   - Write `scope.md` (`## Completion criteria` as a numbered list `1.`, `2.`; every criterion ends with one check tag: `[check: command]`, `[check: file]`, `[check: URL]` or `[check: person]`), do "Scope Review" below, and record before and after the popup.
     - Mark each line the person settled in the interview (an `- Environment:` line, a `Keep it`/`Change it` and a Person-check answer too) with ` (the person's choice)`, on a criterion right before its check tag. L1's reading and answers get no mark.
     - Background questions go in a `## Background research` section: one line each, `- b<n>: <question> — <what it decides in the plan>`. IDs are `b1`–`b4`, each used once, and every question has its own slug (kebab-case, for the note file name). With no questions there is no `## Background research` section (never an empty section or `none`).
     - Write no criterion only L1 can meet after G3 (the final save path, the blueprint update); name that work in the scope as done by L1 after G3.
     - Order: the Korean copy (gates.md "Gate reports"; Korean requests only), the `pre-gate.py` call, the chat report, the popup, the `answer` line.
     - Chat report (shown at that point; gates.md "Gate reports"): `### Overview`, `### Takeaway` (the scope summary: purpose, criteria count and non-goals; the findings applied after Scope Review, as at G1-B; with questions, the line `Background research: <n> questions`), the overview table (with the `Prototype` row when a prototype exists, and the `Background research` row with the questions) the findings table (gates.md "Gate reports") and the pointer line (both printed by `pre-gate.py`); no Details section. The popup follows gates.md's popup text.
     - `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/pre-gate.py" --gate G1-A --task "<absolute task folder>" q="Scope confirmation: <task-id>" rec="Confirm" --data-dir "<data folder>" --task-dir "<task_dir>"` (gates.md "Gate reports"; L1's own report, no writer). Then show the chat report, ending with the findings table and the pointer line it printed.
     - `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" answer gate=G1-A choice="<Confirm/Revise/Abort>" --data-dir "<data folder>" --task-dir "<task_dir>"`
     - On `Revise` with a profile change, follow changes.md "Profile change at the first gate".
     - On Confirm, write `Confirmed <YYYY-MM-DD HH:MM>` in `## Confirmation` of `scope.md`, with the date and minute the `answer` line printed.
   - **Person-check popup:** before the G1-A popup, ask one popup per `[check: person]` criterion.
     - Before it, say in the chat how the person checks it (the steps and where), then ask.
     - The question names the criterion number and text. Choices: `I check it before G3 and tell you (Recommended)` / `I check it after G3`; the Other field takes how and when the person checks it.
     - Record before the popup: `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" ask gate=Q q="How criterion <n> is checked" rec="I check it before G3 and tell you" --data-dir "<data folder>" --task-dir "<task_dir>"`, and after it: `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" answer gate=Q choice="<chosen choice>" --data-dir "<data folder>" --task-dir "<task_dir>"`.
     - Write the answer into that criterion's text, before its tag.
     - On `I check it after G3`, right after the G1-B approval add the `Scope change: criterion <n> is checked by the user later` line (changes.md "Adjust within approved scope").
     - There is no "decide at G3" choice. A person who later finds they cannot check before G3 uses that same line; the verifier cites it as the evidence, and the G3 report lists such criteria.
5. If `scope.md` has a `## Background research` section, do "Background research" below. Then change `phase:` in `.active` to `2` and read `plan.md` (the phase file).

## Background research

Right after G1-A `Confirm`, before `phase:` changes to `2`. Only for the `b<n>` questions the person confirmed with the scope.

1. Record: `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" step n=1B name=Background-research --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"`
2. Call one `my-agent:researcher` per question, all in one message. Prompt: first line `Background question: b<n> <slug>`, then the `scope.md` path, the question, the source criteria (the scope's, or else "official docs and primary sources") and the result path: the note `<slug>.md` in the `background` folder of the task folder, `<task_dir>/<task-id>/background/<slug>.md`.
3. Run the form check on each note (as research.md 3B Merge): the file exists and every item is `- <claim> · <source URL> · "<quote>"` or `- Not found: …`. A `DONE` whose note is missing or fails the form check counts as a worker that stopped once: say so in one line and follow recorder.md "Failure handling". A researcher that stops follows the same section.
4. If a note contradicts the scope (a fact against a criterion or a constraint, e.g. a required API is gone), the plan does not start; the note reopens G1-A with `Revise`, as changes.md "Profile change at the first gate" does, naming the note and the scope line.

## Scope Review

In profiles with G1-A, after `scope.md` is written and before the Person-check popups and the G1-A popup. Not when the profile skips the interview and G1-A (the small task), and not after a G1-A `Revise` (the person made that change).

1. Hand it to `my-agent:scope-reviewer`. Pass: the paths of `intake.md`, `explore.md`, `scope.md`, and the result path `<task_dir>/<task-id>/scope-review.md`. Do not pass the interview or your explanation.
2. Handle the judgment like Plan Review findings (`plan.md` step 2B), with `scope.md` in place of `plan.md`: unmarked findings are applied without a popup. L1 wrote `scope.md`, so L1 makes every fix with Edit and records `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" fix what="Scope Review <severity> <path>:<line>" files=scope.md --data-dir "<data folder>" --task-dir "<task_dir>"`.
   - `REVISE` (any BLOCKER): the popup first, then fix, keep that judgment with `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/archive.py" --task "<absolute task folder>" --name scope-run<its Run: value> --only scope-review.md` (the findings table counts every round), then judge again. The third `REVISE` goes to the person in the G1-A popup, even while delegated approval is on (the popup is unchanged).
   - Marked findings: before the popup, the **findings list table** `# | Severity | Location | Finding | Fix L1 would apply` (not the count table of gates.md "Gate reports"); the popup is laid out as in `plan.md` step 2B, with the SHOULD-FIX line: `Apply all (Recommended)` / `Confirm without applying` / `Pick myself`. `READY FOR CONFIRMATION`: never another round.
   - L1 writes the `## Decisions` lines in `scope-review.md`: `- <severity> <path>:<line> <summary> → applied by L1 | declined`.
