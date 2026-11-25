# Gates: delegated approval details · leave check · gate reports · E escalation

L1 reads this file at the moments SKILL.md "Procedure files" gives.

## Delegated approval details

- **Message while a popup is pending:** a message that asks for delegation ("go ahead without asking me"), typed in the Other field or sent apart, is recorded as the answer first (`prose=1` if sent apart, `other=1` if typed in the Other field), then the confirm popup `Turn on (Recommended)` / `Keep asking me` is shown to the person (`delegate state=on how=message`), and the pending decision is asked again (answered by L1 if on). A take-back message writes `delegate state=off how=person`, and the next popup goes to the person. Delegation stays on after an E answer and after `continue`.
- **Loop cap:** a round is one judgment that sends work back for a fix: Scope Review `REVISE`, Plan Review `REVISE`, Verify FAIL → Execute, Review BLOCKER → fix. Count rounds of the same loop since the latest `delegate state=on` line or E answer. Before a 6th round of the same loop, go to E (`ask gate=E q="Delegated approval: 5 <loop> rounds reached" rec="Give direction"`, to the person). The G3 fix loop has its own cap of 3 (below).
- The lower caps still apply: the third `REVISE` of Scope Review goes to the G1-A popup and of Plan Review to the G1-B popup for the person, and 3 Verify FAILs in a row go to E.
- **G3 under delegated approval:** L1 answers G3, in this order:
  1. Read the findings table the `pre-gate.py` call printed (accept.md). On `findings: FAIL` show the cause; G3 goes to the person.
  2. No open item (BLOCKER 0, SHOULD-FIX 0 and NITPICK 0 open): answer `<Take>` (`Accept`; dev `Commit`), whatever the round count: `ask … rec="<Take>"`, `answer … by=L1`, the chat line `<question> → <Take> (answered by L1)`, then deliver (the commit's G2 dialog still goes to the person). Open risks do not stop the take: list each on a line after the chat line (an unexpected changed path; a criterion `checked by the user later`).
  3. Open items after 3 G3 fix rounds: go to E (`ask gate=E q="Delegated approval: 3 G3 fix rounds reached" rec="Give direction"`, to the person). A round is one G3 that L1 answered `Rework: fix all open items`, counted since the latest `delegate state=on` line or E answer; each light-path round (accept.md) counts as one G3 Rework round.
  4. Otherwise (open SHOULD-FIX or NITPICK items): show no popup; `ask … rec="Rework: fix all open items"`, `answer gate=G3 choice="Rework: fix all open items" … by=L1`, the chat line `<question> → Rework: fix all open items (answered by L1)`, then go on as for that answer.
  - The `rec=` of a G3 that L1 answers is the choice L1 gives. New findings of a fix round are open items of the next G3. A Verify FAIL or a BLOCKER in a round follows the existing rules and caps. After `delegate state=off how=person` the next G3 goes to the person.

## Check before anything leaves

Right before a deliverable leaves the task folder, scan it for secret patterns: copying the deliverable after G3, copying `gate-report.md` in the retrospective, copying the task log back to the main checkout (retro.md item 10), committing (dev profile, or a project that chose to commit `<task_dir>/`).

1. `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/secret-scan.py" <file or folder that leaves>`. If there is no output (exit 0), proceed. Exit 2 (`no such path`): fix the path and scan again.
2. On a hit, show the location (`<file>:<line>: <kind>`) and popup: `Remove those parts and proceed (Recommended)` / `Proceed as is` / `Abort`. Before and after the popup, write `ask gate=Q … rec="Remove those parts and proceed"`/`answer gate=Q` lines.
3. To remove and proceed, L1 fixes only those lines (`fix` line) and repeats item 1.

## Gate reports

At G1-A, G1-B and G3 the chat report is the full gate report; the Report tab adds detail when the monitor runs (no gate starts it). E keeps the overview table followed by `### Details`.

- **Pre-gate call.** Right before each popup, after the Korean copy and (G1-B, G3) the writer, run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/pre-gate.py" --gate <G1-A|G1-B|G3> --task "<absolute task folder>" q="<question>" rec="<recommended choice>" [--report-text "<absolute task folder>/report/<gate>.md"] --data-dir "<data folder>" --task-dir "<task_dir>"`. It writes the `cost` line (G3) and the `ask` line, prints the report text, the findings table under its heading and the pointer line, and opens the Report tab only when `report_open` in `monitor-config.json` is `true`.
  - A plugin script, no harness tool; the gate goes on in every case. Exit 3 (invalid report text) wrote nothing: call the writer again. L1 shows the printed text unchanged; G1-A has no `--report-text`, so L1's own report comes first and the printed findings table and pointer line follow it.
- **Writer** (G1-B, G3): `my-agent:writer` gets the line `Gate report: <G1-B|G3>` and writes `<task folder>/report/<gate>.md`. L1 adds only the dev `Commit message` and `Diff` rows and the cost, as a short table after the printed output, before the popup. A stopped writer: recorder.md "Failure handling".
- **Korean copy.** When the person's request is in Korean, first, before the writer call of G1-B and G3 and the `pre-gate.py` call of G1-A, run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/report-ko.py" --task "<absolute task folder>" todo`.
  - It prints `{key: {sha, en}}` for the overview, criterion and work unit texts whose Korean copy is missing or stale. At G1-A write Korean for each one into `<task folder>/report-ko.json` (`{"items": {"<key>": {"sha": "<printed sha>", "ko": "<Korean>"}}}`), keeping the other items; for G1-B and G3 put the printed output in the writer prompt.
  - The Report tab shows the copy in 한국어 mode and English for any item without a current copy. The English task files stay the source the judges read.
  - In another request language, skip this bullet.
- **Chat report** at these gates: `### Overview` (background and purpose, a few lines of prose in the person's language), `### Takeaway` (Scope, Delivered, Next: one line each; G1-A: the scope summary (purpose, criteria count, non-goals); G1-B: the plan summary (work units, order, estimate)), the table `| Item | Value |` of 5–8 rows, and the pointer line: the line the `pre-gate.py` call printed, as it is. No `### Details`.
- **Table rows:** task and profile; what is being approved; key decisions; counts (files, work units or estimate); open risks or unhandled items (unexpected paths, `Plugin reload` notes, criteria checked by the person later); what each choice leads to. At G1-B the table has a `Models` row: the preset and the recommended change, if any (`Approve` takes it, `Request changes` refuses it); without a change, `standard (definition values)` or the preset name. G1-A and G1-B add a `Prototype` row when a prototype exists. When the scope has background questions, G1-A adds a `Background research` row (`<n> questions (b1, b2)`) and G1-B adds one with the question count and the `Not found` count.
  - G3 in the dev profile adds `Commit message` and `Diff` (`<N> files, +<a>/-<b>` from the last line of `git diff --stat`); the full diff is not printed. G3 in the general and research profiles adds `Save path`.
  - In E, the "Approving" row says what is stuck.
- **Findings table** (G1-A, G1-B, G3 in order; every profile with the gate). The `pre-gate.py` call prints it (`findings.py`) under `### Scope Review findings`, `### Plan Review findings` or `### Review findings`: columns `Severity | Found | Fixed | Open`, one row per severity, shown also when every count is 0. Each cell holds the per-round values joined by `/` (a single round shows one number).
  - On `findings: skipped (…)` (the small task) one line says the judgment was skipped, in place of the table.
  - On a `findings: FAIL` line at G1-A or G1-B show its cause in place of the table; the gate goes on as usual. At G3 show it too (see delegated approval).
- **Popup text.** The question repeats the first two rows. At G1-A, G1-B and G3 it follows the SKILL.md "Question rules" layout (line breaks as written, no blank line) and starts with the label line (recorder.md "Popup label"), then, in this order:
  1. The short question.
  2. `- ` and a counts line `BLOCKER · <n> / SHOULD-FIX · <n> / NITPICK · <n>` (open counts; the words stay in capitals also in another language).
  3. Explanation lines, each its own plain `- ` line of at most two sentences, in the person's language: at G1-A, G1-B and G3, what a SHOULD-FIX is (a problem worth fixing that does not block the gate); at G3 with open items, the `Rework: fix all open items` line (below). The SHOULD-FIX line needs an open SHOULD-FIX; with no open item at G3, neither line is shown.
  4. `- ` and each open item on its own line, starting with its severity; with none, one line says there are No open items. With more than 10, the first 10, then `… and <k> more`.
  5. `- Next: ` and what happens next.

  ```text
  [4B] Review → Deliver · G3
  261120-g3-findings-auto · dev (Router) — commit this change?
  - BLOCKER · 0 / SHOULD-FIX · 1 / NITPICK · 0
  - A SHOULD-FIX is a problem worth fixing that does not block the gate.
  - Rework: fix all open items fixes them, then Verify and Review run again; only the criteria it touches or the items name are judged again. If every open item is a NITPICK small fix, L1 fixes them and only Review runs again.
  - SHOULD-FIX gates.md:36 the cap is not named → name the cap
  - Next: Commit → blueprint update, one commit, retrospective.
  ```
- **G3 with open review items.** Open items are the SHOULD-FIX and NITPICK lines of `review.md` that `## Applied after review` does not list. They set the G3 choices and the recommended one in every profile (dev also: retro.md "Remote update").
  - No open items: `<Take> (Recommended)` / `Rework` / `Abort`, `rec="<Take>"`.
  - Open items: `Rework: fix all open items (Recommended)` / `<Take>` / `Rework` / `Abort`. `Rework: fix all open items` is recommended at every G3 while a SHOULD-FIX or NITPICK is open, also after an earlier Rework answer; `<Take>` only with no open item. L1 gives the same answer under delegated approval ("G3 under delegated approval" above). The `rec=` of the `ask` line is the recommended label.
  - With open items the question has one plain line on `Rework: fix all open items`: the items are fixed, then Verify and Review run again; only the criteria the fix touches or the open items name (`[criterion <n>]`) are judged again, the others keep their earlier verdict. When every open item is a NITPICK small fix, the line adds that L1 fixes them and only Review runs again. With an open SHOULD-FIX with no valid `[criterion <n>]` tag, or with no `changed-files.md`, the line says every criterion is judged again (`Re-judge: all`). It shows for the remote take in place of `Rework`.
  - On `Rework: fix all open items`: ask no follow-up question; the shortfalls are all the open items. Go on as for `Rework` (accept.md step 4B item 7). On `Rework` the person names the shortfalls.

## E escalation

- Conditions: Verify FAIL 3 times in a row, the same work unit (`u<n>` or `b<n>`) stopped twice (`stop:` with the same `unit=` is `end=partial` or `end=error`), a workflow ended with an error, a merge conflict exposes a plan error.
- E always goes to the person, even while delegated approval is on. Chat report: the overview table from "Gate reports" above, then `### Details` with where it is stuck and what was tried. Then record and ask in a popup; its question repeats the first two rows.
  - `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" ask gate=E q="<where it is stuck>" rec="<recommended choice>" --data-dir "<data folder>" --task-dir "<task_dir>"`
  - For Verify FAIL in a row use `q="Verify FAIL x<n>: criterion <n> <one-line reason>"`; the popup body names the criterion and the reason.
  - Popup: `Give direction` / `Change scope` / `Abort` (put the one that fits first, with `(Recommended)`)
  - `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/run-log.py" answer gate=E choice="<chosen choice>" --data-dir "<data folder>" --task-dir "<task_dir>"`
  - After `Give direction` that changes a unit's approach, add `Scope change: u<n> <new approach>` under `plan.md` `## Approval` and its `fix … files=plan.md` line, so plan and deliverable agree.
