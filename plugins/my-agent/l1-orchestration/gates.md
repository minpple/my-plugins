# Gates: delegated approval details · leave check · gate reports · E escalation

L1 reads this file before the first gate popup of a session (G1a, G1b, G3, E), when delegated approval is asked for or turns on, and before a deliverable leaves the task folder (SKILL.md "Procedure files").

## Delegated approval details

- **Message while a popup is pending:** a message that asks for delegation ("go ahead without asking me"), typed in the Other field or sent apart, is recorded as the answer first (`prose=1` if sent apart, `other=1` if typed in the Other field), then the confirm popup `Turn on (Recommended)` / `Keep asking me` is shown to the person (`delegate state=on how=message`), and the pending decision is asked again (answered by L1 if on). A take-back message writes `delegate state=off how=person`, and the next popup goes to the person. Delegation stays on after an E answer and after `continue`.
- **Loop cap:** a round is one judgment that sends work back for a fix: Scope Review `REVISE`, Plan Review `REVISE`, Verify FAIL → Execute, Review BLOCKER → fix. Count rounds of the same loop since the latest `delegate state=on` line or E answer. Before a 6th round of the same loop, go to E (`ask gate=E q="Delegated approval: 5 <loop> rounds reached" rec="Give direction"`, to the person). The G3 fix loop has its own cap of 3 (below).
- The lower caps still apply: the third `REVISE` of Scope Review goes to the G1a popup and of Plan Review to the G1b popup for the person (the popup is unchanged), and 3 Verify FAILs in a row go to E.
- **G3 under delegated approval:** L1 answers G3, in this order:
  1. Run the findings command (`--file review`). On `findings: FAIL` show the cause; G3 goes to the person.
  2. No open item (BLOCKER 0, SHOULD-FIX 0 and NITPICK 0 open): answer `<Take>` (`Accept`; dev `Commit`), whatever the round count: `ask … rec="<Take>"`, `answer … by=L1`, the chat line `<question> → <Take> (answered by L1)`, then deliver (the commit's G2 dialog still goes to the person). Open risks do not stop the take: list each on a line after the chat line (an unexpected changed path; a criterion `checked by the user later`).
  3. Open items after 3 G3 fix rounds: go to E (`ask gate=E q="Delegated approval: 3 G3 fix rounds reached" rec="Give direction"`, to the person). A round is one G3 that L1 answered `Rework: fix all open items`, counted since the latest `delegate state=on` line or E answer.
  4. Otherwise (open SHOULD-FIX or NITPICK items): show no popup; `ask … rec="Rework: fix all open items"`, `answer gate=G3 choice="Rework: fix all open items" … by=L1`, the chat line `<question> → Rework: fix all open items (answered by L1)`, then go on as for that answer.
  - The `rec=` of a G3 that L1 answers is the choice L1 gives; the `<Take>` recommended after a Rework is for the popup shown to the person. New findings of a fix round are open items of the next G3. A Verify FAIL or a BLOCKER in a round follows the existing rules and caps. After `delegate state=off how=person` the next G3 goes to the person.

## Check before anything leaves

Right before a deliverable leaves the task folder, scan it for secret patterns: copying the deliverable after G3, copying `gate-report.md` in the retrospective, committing (dev profile, or a project that chose to commit `<task_dir>/`).

1. `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/secret-scan.py" <file or folder that leaves>`. If there is no output (exit 0), proceed. Exit 2 (`no such path`) means the path is wrong; fix the path and scan again.
2. On a hit, show the location (`<file>:<line>: <kind>`) and popup: `Remove those parts and proceed (Recommended)` / `Proceed as is` / `Abort`. Before and after the popup, write `ask gate=Q … rec="Remove those parts and proceed"`/`answer gate=Q` lines.
3. To remove and proceed, L1 fixes only those lines (`fix` line) and repeats item 1.

## Gate reports

At G1a, G1b and G3 the chat report is the full gate report; the Report tab adds detail when the monitor runs (no gate starts it; the pointer line falls back to the task folder). E keeps the overview table followed by `### Details`.

- **Opening the Report tab.** Right before each of these popups, after its `ask` line (and at G3 after the `cost` line), run `python3 "${CLAUDE_PLUGIN_ROOT}/monitor/open-html.py" --report "<absolute task folder>" --pointer --data-dir "<data folder>"`. It opens the Report tab only when the setting `report_open` in `monitor-config.json` is `true` (the default opens nothing) and prints one line, the pointer line of the chat report.
  - It is a plugin script: no harness tool is used, so it runs the same in Claude Code and Codex. The gate goes on in every case.
- **Korean copy.** When the person's request is in Korean, first, before the `ask` line of G1a, G1b and G3 (at G3 before the `cost` line), run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/report-ko.py" --task "<absolute task folder>" todo`.
  - It prints `{key: {sha, en}}` for the overview, criterion and work unit texts whose Korean copy is missing or stale. For each one write natural Korean into `<task folder>/report-ko.json` (`{"items": {"<key>": {"sha": "<printed sha>", "ko": "<Korean>"}}}`) with the Write tool, keeping the other items. Code names, file names and commands stay as written.
  - The Report tab shows the copy in 한국어 mode and English for any item without a current copy. The English task files stay the source the judges read.
  - In another request language, skip this bullet.
- **Chat report** at these gates: `### Overview` (background and purpose, a few lines of prose in the person's language), `### Takeaway` (Scope, Delivered, Next: one line each; G1a: the scope summary, i.e. purpose, criteria count and non-goals; G1b: the plan summary, i.e. work units, order and estimate), the table `| Item | Value |` of 5–8 rows, and the pointer line: the line the `--pointer` call printed, as it is. No `### Details`.
  - Its forms: `Report: <URL> (opened in the browser: <window|tab>)`; `Report: <URL> (not opened: report_open is off; open it yourself)`; `Report: <URL> (not opened: no browser opened; open it yourself)`; without a URL, `Report: not opened (<reason>); task folder: <absolute task folder>`.
- **Table rows:** task and profile; what is being approved; key decisions; counts (files, work units or estimate); open risks or unhandled items (unexpected paths, `Plugin reload` notes, criteria checked by the person later); what each choice leads to. At G1b the table has a `Models` row: the preset and the recommended change, if any (`Approve` takes it, `Request changes` refuses it); without a change, `standard (definition values)` or the preset name. G1a and G1b add a `Prototype` row when a prototype exists.
  - G3 in the dev profile adds `Commit message` (first line, then `criteria: <numbers>`) and `Diff` (`<N> files, +<a>/-<b>` from the last line of `git diff --stat`); the full diff is not printed. G3 in the general and research profiles adds `Save path` (the exact path).
  - In E, the "Approving" row says what is stuck.
- **Findings table** (G1a, G1b, G3; every profile that has the gate: general, research, dev). Right before the chat report run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/findings.py" --task "<absolute task folder>" --file <scope-review|plan-review|review>` (G1a, G1b, G3). The report holds the printed table under `### Scope Review findings`, `### Plan Review findings` or `### Review findings`: columns `Severity | Found | Fixed | Open`, one row per severity, shown also when every count is 0.
  - On `findings: skipped (…)` (the small task) one line says the judgment was skipped, in place of the table.
  - On a `findings: FAIL` line at G1a or G1b show its cause in place of the table; the gate goes on as usual. At G3 show it too; who answers is the delegated-approval rule.
- **Popup text.** The question repeats the first two rows. At G1a, G1b and G3 it has line breaks between its parts, in this order (the popup shows line breaks as written, as a host shows a multi-line question):
  1. The short question.
  2. A counts line `BLOCKER <n> · SHOULD-FIX <n> · NITPICK <n> (open)`, in the person's language.
  3. Each open item on its own line, starting with its severity; with none, one line says there are No open items. With more than 10, the first 10, then `… and <k> more`.
  4. What happens next.

  ```text
  261120-g3-findings-auto · dev (Router) — commit this change?
  BLOCKER 0 · SHOULD-FIX 1 · NITPICK 1 (open)
  SHOULD-FIX gates.md:36 the cap is not named → name the cap
  NITPICK accept.md:40 repeated word
  Next: Commit → blueprint update, one commit, retrospective.
  ```
- **Prototype** (G1a, and G1b when one exists): built by `my-agent:writer` with the `mock-up` skill files (`${CLAUDE_PLUGIN_ROOT}/skills/mock-up/`), captured with `sh "${CLAUDE_PLUGIN_ROOT}/skills/mock-up/scripts/capture.sh" "<absolute path of prototype/index.html>"`, then opened with `python3 "${CLAUDE_PLUGIN_ROOT}/monitor/open-html.py" "<absolute path of prototype/index.html>" --data-dir "<data folder>"` (no `--task-dir`). A prototype is the local file `<task_dir>/<task-id>/prototype/index.html`. The result goes in the `Prototype` row: `<local path> (opened in the browser: <window|tab>)`, or on a `failed:` line `<local path> (not opened: <reason>; open the file yourself)`. The prototype is not published anywhere. It is remade only when the mock-up changed (otherwise the existing file is opened again).
- **G3 with open review items.** Open items are the SHOULD-FIX and NITPICK lines of `review.md` that `## Applied after review` does not list. They set the G3 choices and the recommended one in every profile (`<Take>` is `Accept`, in the dev profile `Commit`; dev also: retro.md "Remote update").
  - No open items: `<Take> (Recommended)` / `Rework` / `Abort`, `rec="<Take>"`.
  - Open items: `<Take>` / `Rework: fix all open items` / `Rework` / `Abort`. At the first G3 of the task `Rework: fix all open items` is the recommended choice; after a G3 Rework answer in this task (either kind) `<Take>` is. The `rec=` of the `ask` line is the recommended label.
  - On `Rework: fix all open items`: ask no follow-up question; the shortfalls are all the open items. Go on as for `Rework` (accept.md step 8 item 7). On `Rework` the person names the shortfalls.

## E escalation

- Conditions: Verify FAIL 3 times in a row, the same work unit stopped twice (`stop:` with the same `unit=` is `end=partial` or `end=error`), a workflow ended with an error, a merge conflict exposes a plan error.
- E always goes to the person, even while delegated approval is on. Chat report: the overview table from "Gate reports" above (the "Approving" row says what is stuck), then `### Details` with where it is stuck and what was tried. Then record and ask in a popup; its question repeats the first two rows.
  - `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" ask gate=E q="<where it is stuck>" rec="<recommended choice>" --data-dir "<data folder>" --task-dir "<task_dir>"`
  - For Verify FAIL in a row use `q="Verify FAIL x<n>: criterion <n> <one-line reason>"`; the popup body names the criterion and the reason.
  - Popup: `Give direction` / `Change scope` / `Abort` (put the one that fits first, with `(Recommended)`)
  - `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" answer gate=E choice="<chosen choice>" --data-dir "<data folder>" --task-dir "<task_dir>"`
