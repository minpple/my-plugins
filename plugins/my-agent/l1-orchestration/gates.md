# Gates: delegated approval details · leave check · gate reports

L1 reads this file before the first gate popup of a session (G1a, G1b, G3, E), when delegated approval is asked for or turns on, and before a deliverable leaves the task folder (SKILL.md "Procedure files").

## Delegated approval details

- **Message while a popup is pending:** a message that asks for delegation ("go ahead without asking me"), typed in the Other field or sent apart, is recorded as the answer first (`prose=1` if sent apart, `other=1` if typed in the Other field), then the confirm popup `Turn on (Recommended)` / `Keep asking me` is shown to the person (`delegate state=on how=message`), and the pending decision is asked again (answered by L1 if on). A take-back message writes `delegate state=off how=person`, and the next popup goes to the person. Delegation stays on after an E answer and after `continue`.
- **Loop cap:** a round is one judgment that sends work back for a fix: Plan Review `REVISE`, Verify FAIL → Execute, Review BLOCKER → fix, NITPICK fix rounds. Count rounds of the same loop since the latest `delegate state=on` line or E answer. Before a 6th round of the same loop, go to E (`ask gate=E q="Delegated approval: 5 <loop> rounds reached" rec="Give direction"`, to the person). After an E answer the count restarts.
- The lower caps still apply: the third `REVISE` goes to the G1b popup for the person (the popup is unchanged), and 3 Verify FAILs in a row go to E.

## Check before anything leaves

Right before a deliverable leaves the task folder, scan it for secret patterns: copying the deliverable after G3, copying `gate-report.md` in the retrospective, committing (dev profile, or a project that chose to commit `<task_dir>/`).

1. `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/secret-scan.py" <file or folder that leaves>`. If there is no output (exit 0), proceed. Exit 2 (`no such path`) means the path is wrong; fix the path and scan again.
2. On a hit, show the location (`<file>:<line>: <kind>`) and popup: `Remove those parts and proceed (Recommended)` / `Proceed as is` / `Abort`. Before and after the popup, write `ask gate=Q … rec="Remove those parts and proceed"`/`answer gate=Q` lines.
3. To remove and proceed, L1 fixes only those lines (`fix` line) and repeats item 1.

## Gate reports

G1a, G1b and G3 (general and dev) are read on the task's Report tab; the chat report is short. E keeps the overview table followed by `### Details`.

- **Opening the Report tab.** Right before each of these popups, after its `ask` line (and at G3 after the `cost` line), run `python3 "${CLAUDE_PLUGIN_ROOT}/monitor/open-html.py" --report "<absolute task folder>" --data-dir "<data folder>"`. Its one line is `window`, `tab`, `not opened` (the default: the setting `report_open` in `monitor-config.json` is not `true`, so nothing was opened) or `failed: <reason>`.
  - Run `python3 "${CLAUDE_PLUGIN_ROOT}/monitor/open-html.py" --report "<absolute task folder>" --url --data-dir "<data folder>"` only when the first line is `window`, `tab`, `not opened` or `failed: no browser opened`. For any other `failed:` line it does not run `--url` and uses the third pointer form with that reason.
  - Both are plugin scripts run with Bash; no harness tool is used, so the rule runs the same in Claude Code and Codex. The gate goes on in every case.
- **Korean copy.** When the person's request is in Korean, first, before the `ask` line of G1a, G1b and G3 (at G3 before the `cost` line), run `python3 "${CLAUDE_PLUGIN_ROOT}/l4-tools-guards/scripts/report-ko.py" --task "<absolute task folder>" todo`.
  - It prints `{key: {sha, en}}` for the overview, criterion and work unit texts whose Korean copy is missing or stale. For each one write natural Korean into `<task folder>/report-ko.json` (`{"items": {"<key>": {"sha": "<printed sha>", "ko": "<Korean>"}}}`) with the Write tool, keeping the other items. Code names, file names and commands stay as written.
  - `0 to translate` means nothing to do. The Report tab shows the copy in 한국어 mode and English for any item without a current copy. The English task files stay the source the judges read; the copy is a task record like the others.
  - In another request language, skip this bullet.
- **Chat report** at these gates: `### Overview` (background and purpose, a few lines of prose in the person's language), `### Takeaway` (Scope, Delivered, Next: one line each; G1a: the scope summary, i.e. purpose, criteria count and non-goals; G1b: the plan summary, i.e. work units, order and estimate), the table `| Item | Value |` of 5–8 rows, and one pointer line in one of the three pointer forms below. No `### Details`.
  - After `window` or `tab`: `Report: <URL> (opened in the browser: <window|tab>)`.
  - After `not opened`: `Report: <URL> (not opened: report_open is off; open it yourself)`. After `failed: no browser opened`: `Report: <URL> (not opened: no browser opened; open it yourself)`.
  - After any other `failed:` line (from either call): `Report: not opened (<reason>); task folder: <absolute task folder>`.
- **Table rows:** task and profile; what is being approved; key decisions; counts (files, work units or estimate); open risks or unhandled items (unexpected paths, `Plugin reload` notes, criteria checked by the person later); what each choice leads to. At G1b the table has a `Models` row: the preset and the recommended change, if any (`Approve` takes it, `Request changes` refuses it); without a change, `standard (definition values)` or the preset name. G1a and G1b add a `Prototype` row when a prototype exists.
  - G3 in the dev profile adds `Commit message` (first line, then `criteria: <numbers>`) and `Diff` (`<N> files, +<a>/-<b>` from the last line of `git diff --stat`); the full diff is not printed. G3 in the general and research profiles adds `Save path` (the exact path).
  - In E, the "Approving" row says what is stuck.
- The popup question text repeats the first two rows, e.g. "261101-fix-tally · dev (Router) — confirm the scope (6 criteria)?".
- **Prototype** (G1a, and G1b when one exists): built by `my-agent:writer` with the `mock-up` skill files (`${CLAUDE_PLUGIN_ROOT}/skills/mock-up/`), captured with `sh "${CLAUDE_PLUGIN_ROOT}/skills/mock-up/scripts/capture.sh" "<absolute path of prototype/index.html>"`, then opened with `python3 "${CLAUDE_PLUGIN_ROOT}/monitor/open-html.py" "<absolute path of prototype/index.html>" --data-dir "<data folder>"` (no `--task-dir`). A prototype is the local file `<task_dir>/<task-id>/prototype/index.html`. The result goes in the `Prototype` row: `<local path> (opened in the browser: <window|tab>)`, or on a `failed:` line `<local path> (not opened: <reason>; open the file yourself)`. The prototype is not published anywhere. It is remade only when the mock-up changed (otherwise the existing file is opened again). The G1b Report view links it through the monitor.
