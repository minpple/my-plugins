# Decisions

## Constraints
- The write guard does not change: the coder writes nothing in the task folder, and hooks, permission rules and allowed write paths do not change — only L1 stores notes, so the guard is not weakened (261117-notepads-learnings-handoff)
- Add no new gate, popup or question to the person. The number of questions per task stays fixed — design principle (261117-notepads-learnings-handoff)
- Add no new agent and no new run-log line kind (261117-notepads-learnings-handoff)
- SKILL.md stays under 12,500 characters and each rule file L1 reads at once stays under 11,500 characters — tests enforce this (261117-notepads-learnings-handoff)
- Runtime rules carry no temporary exception or workaround wording; the architecture document changes in the same commit so the runtime works as designed (261117-notepads-learnings-handoff)
- The worker turn limit, the "a stopped worker is retried once, then E" handling and the E conditions do not change (261117-notepads-learnings-handoff)
- Judge agents receive only paths and criteria (261117-notepads-learnings-handoff)
- Text in the repository is English. Only the Korean README and the Korean feature overview page are exceptions (261117-notepads-learnings-handoff)
- A release puts the feature and the version-location changes in one commit (261117-notepads-learnings-handoff)
- Steps show as phase digit plus a letter restarting in each phase: ① A Intake, B Explore → Scope; ② A Plan, B Plan Review; ③ A Execute, B Merge; ④ A Verify, B Review → Deliver (`1A`…`4B`); phases keep their numeric ①–④ display and step names are not renamed — the person chose this scheme at Scope (261120-tray-step-letters)
- The state record, the run log, the `/api/tasks` data and the rule files (SKILL.md, phase and profile files, agent definitions, design doc) keep the numeric steps 1–8; letters are worked out only when displaying — they are identifiers (261120-tray-step-letters)
- The letter tables (web `STEP_CODE`, Swift `stepCodes`, architecture template `STEP_CODE`) are explicit literals, not a formula, and are changed together with the name tables (web `STEP_NAME`, Swift `stepNames`); tests compare them — duplicated surfaces must not drift (261120-tray-step-letters)

## Non-goals
- The tray mini window List shows no step text and no phase display; the Windows tray is not changed — placeholder only, and not part of the request (261120-tray-step-letters)
- The status colors and the 8-cell progress bar are not changed; no letters for gates and no renaming of steps or phases — out of the request (261120-tray-step-letters)
- No notes for researcher and writer work units — only handoff between coder units is covered (261117-notepads-learnings-handoff)
- The coder does not write notes itself during work, and no note survives when a unit stops at the turn limit — this keeps the write guard (261117-notepads-learnings-handoff)
- Notes are not shown in the monitor or the Report tab (261117-notepads-learnings-handoff)
- Notes are not used for the blueprint update or the retrospective (261117-notepads-learnings-handoff)
- The repository does not name other tools or their features (261117-notepads-learnings-handoff)

## Decisions
- Handoff between work units: L1 stores the notes part of the coder final report in the single file `coder-notes.md` in the task folder and passes its path only to later coder calls. Alternatives not taken: the coder writing the file itself (conflicts with the write guard, and a worktree coder cannot write to the task folder), one notes file per unit — architecture document Q31 (261117-notepads-learnings-handoff)
- Notes are written and read during the task. This differs from the blueprint and the retrospective, which are written after the task ends (261117-notepads-learnings-handoff)
- The notes part is stored up to 10 lines not counting blank lines; beyond that, the first 10 lines and one truncation line are stored. Notes are treated as data, and the plan wins when it conflicts with a note (261117-notepads-learnings-handoff)
- Coder units run through a workflow also have the script return the notes part together with the first line, and L1 stores it by the same rule — applied from plan-review SHOULD-FIX (261117-notepads-learnings-handoff)
- Like the other records in the task folder, the notes file is kept with the task folder and is not deleted during a revision; entries are told apart by the rev number in their label (261117-notepads-learnings-handoff)
- Inside a step circle under a phase heading (web Dashboard and replay step lists, architecture page rail and step cards) the letter shows alone (`A`); standalone text shows the full label (`3A Execute`); a step outside 1–8 shows its raw number — chosen at Plan Review (261120-tray-step-letters)
- Text that arrives already formatted (the log item `step 5 · Execute`, the gate-tally steps cell) is converted on the web page only (`stepTx`, `stepsText`); `events.py`, `report.py`, `ma_gate_report.py` and the gate-tally files stay numeric — chosen at Plan Review (261120-tray-step-letters)
- The feature pages' walkthrough nodes keep the phase digit (two nodes per phase show the same digit); only the phase and step sentence uses the letters — chosen at Plan Review (261120-tray-step-letters)
- Rule-file excerpts and the design-doc flow text on the architecture page stay numeric, so a card can read `Step 3A · 5. Execute` — they are rule and design text (261120-tray-step-letters)
- Every plugin version raise adds a new entry at the start of the architecture document status line, and `test_arch_doc` pins it (`v0.60`, plugin 0.20.0) — Scope change at Execute (261120-tray-step-letters)
