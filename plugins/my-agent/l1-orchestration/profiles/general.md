# General profile (general)

Multi-step tasks that fit neither the research nor the dev profile. On the normal path the person is asked 3 times: G1a, G1b, G3; for a small task, 2 times: G1b, G3 (not counting questions asked only the first time, such as the task location and `.gitignore`).

## Rules per phase

| Step | General profile |
|---|---|
| 2 Explore → Scope | Hand Explore to explorer only when the request is about existing files or a project. The Scope interview settles four things in `scope.md`: **purpose and users** (`## Purpose and users`: a `Background:` paragraph, a `Purpose:` paragraph, then the users line), **completion criteria** (a numbered `## Completion criteria` list; each criterion ends with one check tag: `[check: command]`, `[check: file]`, `[check: URL]` or `[check: person]`), **non-goals** (`## Non-goals` bullets) and the **deliverable location** (`## Deliverable`, one line ``- Deliverable location: `<path>` ``, an absolute path (no `~`, no relative path); after approval, the hook asks about writes outside the task location that fall outside this path). If the request covers all of them, skip the interview. Then Scope Review (`define.md` "Scope Review"), and confirm with G1a. |
| Small task exception | If the task creates or changes fewer than 3 files (from `explore.md`, or from the request when Explore was skipped), and the request already answers purpose and users, completion criteria, non-goals and the deliverable location (an absolute path): skip the Scope interview, Scope Review and G1a. L1 passes a 5-line summary (purpose, numbered completion criteria with check tags, non-goals, deliverable location, constraints) to architect, which puts it at the top of `plan.md` as `## Scope summary` and `## Completion criteria`. Skip Plan Review and write `SKIPPED small task` in `plan-review.md`. State the decision and its reason in one line, on the line after the Intake report. There is no Background research for a small task (a web fact that changes the plan means it is not small). |
| 3 Plan | A work unit is one part of the deliverable, taken by the agent that fits it: `my-agent:writer` (a draft under `work/`), `my-agent:researcher` (facts from the web, one note `work/<slug>.md` per unit) or `my-agent:coder` (code: files to change in the task location and the check commands). Every `[check: command]` criterion names its command, in the criterion or in a unit that carries it. The mock-up is a sample of the deliverable (e.g. the first few rows of a table, a document's outline and a sample paragraph). |
| 4 Plan Review | May be skipped if the work units change fewer than 3 files in total. If skipped, record the reason in `plan-review.md` (a small task: `SKIPPED small task`). Findings are handled as in `plan.md` step 4. |
| G1b | Plan approval. The `scope.md` summary was confirmed at G1a, so do not ask again; show it along with the plan. For a small task, show the 5-line summary with it; G1b is then the first gate. |
| 5 Execute | Use subagents. Do not use a workflow. A work unit's web research starts after G1b approval; the only earlier web research is Background research for the questions confirmed at G1a (define.md). A coder unit changes its files in place in the task location and does not commit; call it without `isolation: "worktree"`. Each coder unit has a parallel group of its own, so coder units run one after another. |
| 6 Merge | If the deliverable is a document and there are two or more work units, L1 hands the plan's last work unit (`my-agent:writer`) out in 6 Merge, and that writer combines the earlier units' results into one `work/final.md` (or one file under `work/` that fits the deliverable format). L1 does not combine; it only checks. Basic checks: each writer and researcher unit has a result file, each completion criterion has a matching part, and every item in a researcher note has the form `- <claim> · <source URL> · "<quote>"` or `- Not found: …` (hand a note with a broken format back to its researcher). |
| 7 Verify | PASS/FAIL per criterion. Not skipped. The changed-file map lists the files under `work/` and `deliverable/` and the files coder units changed in place. verifier runs the command of each `[check: command]` criterion, and opens the sources of the researcher notes to confirm the quotes. |
| 8 Review → Deliver | Result summary and quality judgment. Not skipped. Save location: the deliverable location in `scope.md`, or `deliverable/` if none. Code a coder unit changed in place is already in the task location: it is not copied, and the `Save path` row of the G3 report names those files with the save location. Do not save to the Obsidian vault. |

## Agents used

Names are the names used to call them. The definition files are in the plugin's `l2-design-judge/agents/` and `l3-workers/agents/`.

| Agent | Steps | Result |
|---|---|---|
| `my-agent:explorer` | 2 | `explore.md` |
| `my-agent:scope-reviewer` | 2 (before G1a) | `scope-review.md` |
| `my-agent:architect` | 3, G1b revisions | `plan.md` |
| `my-agent:plan-reviewer` | 4 | `plan-review.md` |
| `my-agent:researcher` | 2 (Background research, only `b<n>` confirmed at G1a) and 5 (units that need research, after G1b) | step 2: `background/` notes; step 5: `work/` notes (claim · source URL · quote) |
| `my-agent:writer` | 5, 6 (the last combining unit), prototype | `work/` drafts, `work/final.md`, `prototype/index.html` |
| `my-agent:coder` | 5 (units that need code) | code changed in place in the task location (not committed) |
| `my-agent:verifier` | 7 | `verify.md` |
| `my-agent:reviewer` | 8 | `review.md` |
