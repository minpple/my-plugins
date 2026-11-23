# ② Plan: 3 Plan · 4 Plan Review → G1b

## 3. Plan

1. Record: `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" step n=3 name=Plan --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"`
2. Hand it to `my-agent:architect`. Pass: the paths of `intake.md`, `explore.md` (and `scope.md`; for a small task, its 5-line summary), the preset name from `intake.md` `Models:` with the lines of `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/agent-models.py" show --profile <p> --preset <name> --data-dir "<data folder>"` (none when there is no `Models:` line), and the result path `<task_dir>/<task-id>/plan.md`.
3. Sections `plan.md` must have (if one is missing, have architect rewrite only that section):
   - a lead paragraph right after the `# Plan: <task-id>` title: one or two sentences on what the plan builds (not a `Profile:` line or a pointer to the criteria); the G1b Report view shows it as the plan summary
   - `## Scope summary` (small task): purpose, non-goals
   - `## Completion criteria`: numbered list `1.`, `2.`, each criterion line ending with its check tag (small task; other tasks have it in `scope.md`)
   - `## Work units`: per unit, a `### u<n> <name>` heading, the agent in charge, the list of files to change, the parallel group, `- Status: pending` (when rewriting, `done` for units whose results `## Existing work` keeps as they are)
   - `## Reference files`: files outside the task folder that agents may read (scope-guard allows every worker's reads by this list)
   - `## Mock-up` (**required**): first line `Kind: <kind>`, then a sample of the deliverable. Both the normal case and the exception cases in the scope, each tagged with its completion criterion number
   - `## Models` (with a `Models:` line in `intake.md`): the preset name and a table of the agents the plan uses (model, effort, note), plus a `Recommendation:` line when architect proposes a change; without a preset, `Preset: standard (definition values)`
   - `## Prototype`: needed / not needed, and why
   - `## Estimate`: number of subagents, workflow steps and agent count
   - `## Existing work`: only when rewriting for a revision (rev). For each deliverable already made: keep / revise / discard
   - `## Approval`: left empty
   - `## Revisions`: if the previous `plan.md` had it, carried over as is at the very end
4. If work units in the same parallel group change the same files, have them reordered to run in sequence.

## 4. Plan Review

1. Record: `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" step n=4 name=Plan-Review --model <main session model ID> --data-dir "<data folder>" --task-dir "<task_dir>"`
2. **Plan gaps:** run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/plan-lint.py" --task "<absolute task folder>"`, also when Plan Review is skipped. Each `plan-lint: FAIL <gap>` line is fixed before anything else, like a BLOCKER in item 4 (a missing check tag in a confirmed `scope.md` is an L1 edit there; record `fix what="Plan gaps <gap>"`), then run it again until `plan-lint: ok`. It is not a Plan Review round. The G1b hook runs the same check and denies the `Approved` line while a gap is left. Whether to skip Plan Review follows the profile file. If skipped, write `SKIPPED <reason>` in `plan-review.md`.
3. Hand it to `my-agent:plan-reviewer`. Pass: the paths of `plan.md`, `intake.md`, `explore.md`, the same `agent-models.py show` lines as for architect, and the result path `plan-review.md`. Do not pass architect's explanation.
4. Handle the judgment the same way in every profile. "Small" is the SKILL.md level-table size (2 task files or fewer, about 10 lines); a finding that turns out larger goes to architect.
   - **L1 edit of `plan.md`** (small): archive per "Rewrite before approval" below, edit `plan.md` with Edit (SKILL.md "Tool choice"), then record `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" fix what="Plan Review <severity> <path>:<line>" files=plan.md before=G1b archive=<archive folder> --data-dir "<data folder>" --task-dir "<task_dir>"`. **Architect rewrite** (larger): archive and write the `revision … before=G1b` line as in that section, then pass the `plan-review.md` path to architect.
   - `REVISE` (any BLOCKER): small → L1 edit, otherwise architect rewrite; then judge again. If the third `REVISE` comes, show that judgment in the G1b popup and leave it to the person, even while delegated approval is on (SKILL.md "Delegated approval"; the popup is unchanged).
   - `READY FOR APPROVAL`: never another Plan Review round. Apply what is chosen below, then go to G1b.
     - NITPICK only: apply them without a popup (L1 edit if small, else architect) and go to G1b.
     - Any SHOULD-FIX: first show the findings in the chat as a **findings list table**, one row per finding: `# | Severity | Location | Finding | Fix L1 would apply` (not the count table of gates.md "Gate reports"). Then ask one popup over the whole list (NITPICKs included), recorded with `ask gate=Q … rec="Apply all"` and `answer gate=Q`: `Apply all (Recommended)` / `Approve without applying` / `Pick myself`. Apply the chosen items (L1 edit if small, else architect), then go to G1b.
   - L1 writes the `## Decisions` lines in `plan-review.md`; architect does not write that file. Each applied or declined item is one line in `## Decisions`: `- <severity> <path>:<line> <summary> → applied by L1 | applied by architect | declined`.

## G1b plan approval

1. **Chat report** (shown after the Report tab is opened, item 4; gates.md "Gate reports"): `### Overview`, `### Takeaway` (the plan summary: work units, order and estimate; in a small task also the scope summary), the overview table with its `Models` row (the preset and the recommended change, if any) and a `Prototype` row when a prototype exists, the findings table (gates.md "Gate reports") and the pointer line. No Details section and no full mock-up in the chat. Put the findings applied after Plan Review in the Takeaway ("Applied after Plan Review: 2 NITPICK (plan.md:41, plan.md:77)"). If a work unit has a `- Plugin reload: needed (<what>)` line, put a `Plugin reload` note in the risks row: `/reload-plugins` (or a new session) is needed after that unit. The popup follows gates.md's popup text.
2. If `## Prototype` is "needed", popup: `Make a prototype (Recommended)` / `Mock-up is enough` / `Plan change`.
   - `Plan change` is the same as item 6, Request changes.
   - To make one, add a `Prototype: requested` line inside the `plan.md` `## Prototype` section with Edit and hand `my-agent:writer` the output path `<task_dir>/<task-id>/prototype/index.html`, the plan's `## Mock-up` and the paths `${CLAUDE_PLUGIN_ROOT}/skills/mock-up/SKILL.md`, `${CLAUDE_PLUGIN_ROOT}/skills/mock-up/templates/canvas.html` and the matching `${CLAUDE_PLUGIN_ROOT}/skills/mock-up/references/*.md`. The writer reads them, builds the file from the template and references and keeps the capture boot script (SKILL.md "Tool choice" for the checks).
   - L1 then runs `sh "${CLAUDE_PLUGIN_ROOT}/skills/mock-up/scripts/capture.sh" "<absolute path of prototype/index.html>"`, reads `prototype/index.png` and hands the file back to the writer for a fix, at most 3 times. On a non-zero capture exit (for example no Chromium browser) it states the line and goes on without a PNG.
   - If a G1a prototype exists (`scope.md`), remake it only if the mock-up changed.
   - L1 reads that file to check it, then runs `python3 "${CLAUDE_PLUGIN_ROOT}/monitor/open-html.py" "<absolute path of prototype/index.html>" --data-dir "<data folder>"`, and shows the local path with the script's line (gates.md "Gate reports"); on a `failed:` line it carries on and the person opens the path. Nothing is published, so no secret scan here.
3. **Hosts:** for each `- Needs host: <name>` line in `plan.md`, run `curl -sI -m 10 https://<name>` once (not again for a host that already answered in this task). For hosts that do not answer (a proxy refusal, a timeout), ask one popup naming them before the approval popup, with `ask gate=Q … rec="I allow the hosts first"`/`answer gate=Q` lines: `I allow the hosts first (Recommended)` / `Plan change` / `Go on as is`. After the first, check again when the person says it is done; `Plan change` is item 6.
4. Record before and after the approval popup. Order: the Korean copy (gates.md "Gate reports"; Korean requests only), the `ask` line, the Report tab, the chat report of item 1 with the pointer line, the popup, the `answer` line.
   - `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" ask gate=G1b q="Plan approval: <task-id>" rec="Approve" --data-dir "<data folder>" --task-dir "<task_dir>"`
   - Then open the Report tab (`open-html.py --report … --pointer`, gates.md "Gate reports") and show the chat report (item 1), ending with the pointer line it printed.
   - Popup: `Approve (Recommended)` / `Request changes` / `Abort`
   - `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" answer gate=G1b choice="<chosen choice>" --data-dir "<data folder>" --task-dir "<task_dir>"`
5. **Approve:** Write `- Approved <YYYY-MM-DD HH:MM> G1b` under `## Approval`. Take the date and minute from the line the `answer` command printed (no `date` call) and write the value with the Edit tool, without command substitution (SKILL.md "Tool choice"; the G1b hook asks for a Bash write containing `$(…)` as a command whose write target it cannot tell). The `## Models` rows now apply; a recommended change is part of the approval, and `Request changes` refuses it. Change `phase:` in `.active` to `3` and read `build.md`.
6. **Request changes:** a small change (SKILL.md level-table size) is an L1 edit of `plan.md`; otherwise architect rewrites. Both follow "Rewrite before approval" below. Go back to item 1; Plan Review runs again only after a BLOCKER fix. In a small task G1b is the first gate: if the person wants a different profile, follow changes.md "Profile change at the first gate". If the request changes the confirmed scope, take Revise this task in that section. Remake the prototype only if the mock-up changed.
7. **Abort:** the "Abort" procedure in changes.md.

## Rewrite before approval

Every case where architect rewrites `plan.md` before G1b approval: G1b `Request changes`, Plan Review `REVISE`, applying Plan Review findings, prototype popup `Plan change`. "current rev" and "Archive" are defined in `recorder.md` "Revision records and archive".

- Do not ask the kind. Before handing it back to architect, archive to `archive/<time>-rev<current rev>-draft/` and write a `revision rev=<current rev> before=G1b why=… archive=…` line (an L1 edit: the variant below). The rev does not go up, and nothing is written to `## Revisions`. If the request changes the confirmed scope (`scope.md`), it is `Revise this task` in `changes.md` "In-flight revision".
- **L1 edit variant:** a small change (level-table size: 2 task files or fewer, about 10 lines) can be made by L1 with the Edit tool instead. Same archive, but write a `fix … files=plan.md before=G1b archive=…` line instead of `revision`. Plan Review again only after a BLOCKER fix, never after `READY FOR APPROVAL`. A NITPICK that turns out larger goes to architect.
