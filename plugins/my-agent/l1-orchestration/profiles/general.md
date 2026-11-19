# General profile (general)

Multi-step tasks that fit neither the research nor the dev profile. On the normal path the person is asked twice: G1b and G3 (not counting questions asked only the first time, such as the task location and `.gitignore`).

## Rules per phase

| Step | General profile |
|---|---|
| 2 Explore → Scope | Ask: purpose, completion criteria (each ends with one check tag: `[check: command]`, `[check: file]`, `[check: URL]` or `[check: person]`), non-goals, deliverable location. If the request covers all of them, skip the interview. Do not ask G1a separately, and no Scope Review (plan-reviewer judges the scope summary). Write the deliverable location in the scope summary as one line ``- Deliverable location: `<path>` ``, an absolute path (no `~`, no relative path). After approval, the hook asks about writes outside the task location that fall outside this path. |
| 3 Plan | Put the scope summary and `## Completion criteria` at the top of `plan.md`. A work unit is one part of the deliverable, taken by the agent that fits it: `my-agent:writer` (a draft under `work/`), `my-agent:researcher` (facts from the web, one note `work/<slug>.md` per unit) or `my-agent:coder` (code: files to change in the task location and the check commands). Every `[check: command]` criterion names its command, in the criterion or in a unit that carries it. The mock-up is a sample of the deliverable (e.g. the first few rows of a table, a document's outline and a sample paragraph). |
| 4 Plan Review | plan-reviewer judges the scope summary against the request (there is no Scope Review) and then the plan. May be skipped if the work units change fewer than 3 files in total. If skipped, record the reason in `plan-review.md`. Findings are handled as in `plan.md` step 4. |
| G1b | Approve the scope summary and the plan at once; the `### Takeaway` carries the scope summary with the plan summary. It is the first gate, so show the task ID with it. |
| 5 Execute | Use subagents. Do not use a workflow. Start web research only after G1b approval. A coder unit changes its files in place in the task location and does not commit; call it without `isolation: "worktree"`. Each coder unit has a parallel group of its own, so coder units run one after another. |
| 6 Merge | If the deliverable is a document and there are two or more work units, L1 hands the plan's last work unit (`my-agent:writer`) out in 6 Merge, and that writer combines the earlier units' results into one `work/final.md` (or one file under `work/` that fits the deliverable format). L1 does not combine; it only checks. Basic checks: each writer and researcher unit has a result file, each completion criterion has a matching part, and every item in a researcher note has the form `- <claim> · <source URL> · "<quote>"` or `- Not found: …` (hand a note with a broken format back to its researcher). |
| 7 Verify | PASS/FAIL per criterion. Not skipped. The changed-file map lists the files under `work/` and `deliverable/` and the files coder units changed in place. verifier runs the command of each `[check: command]` criterion, and opens the sources of the researcher notes to confirm the quotes. |
| 8 Review → Deliver | Result summary and quality judgment. Not skipped. Save location: the deliverable location in the scope summary, or `deliverable/` if none. Code a coder unit changed in place is already in the task location: it is not copied, and the `Save path` row of the G3 report names those files with the save location. Do not save to the Obsidian vault. |

## Agents used

Names are the names used to call them. The definition files are in the plugin's `l2-design-judge/agents/` and `l3-workers/agents/`.

| Agent | Steps | Result |
|---|---|---|
| `my-agent:explorer` | 2 | `explore.md` |
| `my-agent:architect` | 3, G1b revisions | `plan.md` |
| `my-agent:plan-reviewer` | 4 | `plan-review.md` |
| `my-agent:researcher` | 5 (units that need research, only after G1b) | `work/` notes: claim · source URL · quote |
| `my-agent:writer` | 5, 6 (the last combining unit), prototype | `work/` drafts, `work/final.md`, `prototype/index.html` |
| `my-agent:coder` | 5 (units that need code) | code changed in place in the task location (not committed) |
| `my-agent:verifier` | 7 | `verify.md` |
| `my-agent:reviewer` | 8 | `review.md` |
