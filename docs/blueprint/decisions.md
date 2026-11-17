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

## Non-goals
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
