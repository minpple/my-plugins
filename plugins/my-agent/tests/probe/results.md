# Probe results (build step 0, 2026-10-25)

- Practice project: `~/dev/labs/my-agent-sandbox/` (git repository, `docs/agent/.active` → `261025-probe-task`)
- Run: `probe/run-probes.sh r1 … r7` — `claude -p --plugin-dir ~/dev/my-agent --model haiku --permission-mode default`, stream-json output in `.probe/run-<r>.json`
- Records: `probe-log.py` writes hook input to `.probe/<label>.jsonl`. The real hooks (`hooks/hooks.json`) are on too, so run-log lines are checked as well
- Agent: `probe/agents/probe-worker.md` (haiku, effort low, Bash·Read, maxTurns 3)

## Section 4.13 items

| # | Question | Run | Evidence (file · field) | Answer |
|---|---|---|---|---|
| 1 | Do plugin `SubagentStart`/`SubagentStop` hooks run for `my-agent:*`? | r1 | `agent_type: my-agent:probe-worker` in `SubagentStart.jsonl`·`SubagentStop.jsonl`, run-log `start:`/`stop:` lines | **Yes.** Matched by matcher `^my-agent:` |
| 2 | The `cwd` in the hook input when a worktree coder ends | r2 | `cwd` in `SubagentStart.jsonl`·`SubagentStop.jsonl` = `<repo>/.claude/worktrees/agent-<id>`; that folder's `.git` is a `gitdir:` file | **The worktree path.** No `.active` there, so records were missing at first → fixed `ma_active.find_active` to follow `gitdir:` and read the main tree's `.active`. Rerun r2 shows `start:`/`stop:` lines |
| 3 | Do agents inside a workflow fire these events? | r10 | `start:`/`stop:` for 2 workflow `agent()` calls in the run-log (`configured=sonnet`, `actual=claude-sonnet-5-5`). No `call:` line | **Yes** (when `agentType` is given). F29 |
| 4 | Do skill frontmatter hooks also run inside subagents? | r3 | `skill-pretool.jsonl`: only 1 `Agent` call from the main session, no `agent_id`. No record for the subagent's `Bash` calls | **No.** Rules that must also block subagents go in plugin hooks (F9 decision kept) |
| 5 | Does the call argument `isolation: "worktree"` apply to custom agents? | r2 | `tool_input.isolation: worktree` in `PreToolUse.jsonl`; the subagent's `pwd` output and `cwd` are `.claude/worktrees/agent-<id>` | **Yes** |
| 6 | Do background subagents end when the session ends? | r4, interactive 2026-10-25 | Interactive `/exit` shows running background tasks (shells, agents) and asks `Exit and stop tasks` / `Move to background and exit` / `Stay`. Picking the default (stop) stops them: the `sleep 60; echo late` shell disappeared and `late` never printed | **Answered (F31).** By default they stop together. To keep them, pick `Move to background` |
| 7 | Do G1·G3 popups (`AskUserQuestion`) trigger `claude-sessions` notifications? | 2026-10-25 interactive (tmux) | Put a temporary `Notification` hook (matcher `""`, appends stdin to a file) in the sandbox `.claude/settings.json`, showed a popup and waited 100 seconds | **Yes.** When the popup appeared, one event: `notification_type: permission_prompt`, `message: "Claude needs your permission"`. It is in the `claude-sessions` matcher, so a Mac notification goes out. The user was away and did not get it on another device ("it didn't come") — expected, since it is a Mac notification. Temporary hook removed (F34) |
| 8 | Is `${CLAUDE_PLUGIN_ROOT}` replaced in skill frontmatter hook commands? | r3 | `env.CLAUDE_PLUGIN_ROOT = ~/dev/my-agent` in `skill-pretool.jsonl`. Single-quoted `'${CLAUDE_PLUGIN_ROOT}'` passed as an argument stays as is | **It comes in as an environment variable** (not text substitution). Written in double quotes `"${CLAUDE_PLUGIN_ROOT}"`, the shell expands it → can replace `$HOME/dev/my-agent` in section 4.7.1 |
| 9 | Does the status line `cost.total_cost_usd` include subagent cost? | scenario runs 2026-10-25 | General: shown $2.12, main transcript list price $1.63 + subagents $0.40 = $2.03. Research: shown $5.14, main $1.99 + subagents $2.01 = $4.00 | **Answered (F32).** It does. The shown value is clearly larger than the main-only value (the remaining gap is taken to be calls outside the transcript, such as WebFetch summaries) |
| 10 | Can a workflow `agent()` name a plugin agent, and what is `agent_type` then? | r10 (2026-10-25, user approval) | `agent(…, {agentType: 'my-agent:explorer'})` → SubagentStart matcher `^my-agent:` runs, scope-guard blocks that agent's `Read /etc/hosts` ("scope-guard: Outside the read scope of explorer") | **Yes.** `agent_type` is `my-agent:explorer`. Meets the protection condition in section 4.6 → `build.md` workflow rules. F29 |
| 11 | With both `"skills": ["./"]` and `skills/monitor/`, do both show? | r5 | init event in `run-r5.json`, `skills`: `my-agent:my-agent`, `my-agent:monitor`, `my-agent:probe-skill`; `agents`: `my-agent:probe-worker` | **Yes** |

## Other facts confirmed

| Fact | Run | Evidence | Applied |
|---|---|---|---|
| `PermissionRequest` runs in `-p` too, and its input has `agent_id`, `agent_type`, `permission_mode`, `effort`, `permission_suggestions` | r6 | `PermissionRequest.jsonl` | Resolves the G2 [unverified] in section 4.7.2. `permission-log.py` uses the input's `agent_id` first |
| After a G2 denial there is no `PostToolUse`, so no `answer:` line is made | r6 | 2 `ask:` lines in the run-log, no `answer:` | As designed |
| `SubagentStart` input has no `permission_mode`. `SubagentStop` has `permission_mode`, `effort: {"level": …}`, `background_tasks`, `session_crons`, `stop_hook_active` | r1 | `SubagentStart.jsonl`, `SubagentStop.jsonl` | Removed `mode=` from `start:` and added `mode=`, `effort=` to `stop:` |
| An agent that ended by maxTurns gets no `SubagentStop`. The meta file `~/.claude/projects/<proj>/<session>/subagents/agent-<id>.meta.json` has `"finished": true`, and the last assistant entry's `stop_reason` is `tool_use` (a normal end is `end_turn`) | r4, r7 | No such id in `SubagentStop.jsonl`, meta and transcript files | `lib/ma_subagent.sweep` writes `stop: … end=partial` during `run-log.py` and subagent-log start/stop. `run-log.py` prints one `PARTIAL:` line |
| The transcript assistant entry keeps `effort` | r1 | Subagent transcript `effort: low` | Resolves [unverified] 4 in section 4.7.2 |
| In `-p`, an `Agent` call is async even without `run_in_background` (`status: async_launched`, meta `requestShape: background`). Then `PostToolUse(Agent)` has no result. A sync call's `tool_response` has status, totalTokens, usage, content | r1, r7 | `PostToolUse.jsonl`, meta files | Leave records to the Subagent events and sweep; do not use `PostToolUse(Agent)` |
| `result=` (first line of the last message) may not be a verdict word (r1: "The command \`pwd\` returned:") | r1 | run-log `stop:` line | Step 4 agent definitions get a "verdict word on the first line" rule. The monitor checks `startswith('FAIL')` |
| In `-p`, a `Skill` the model invokes needs permission. If denied ("Skill tool permission denied"), neither the skill content nor its frontmatter hooks are registered | live-t5, live-t5b (2026-10-25) | `claude --debug hooks` log: only scope-guard ran on `PreToolUse:Write` | F28. `-p` tests pass `--allowedTools Skill`. Interactively, the user allows it |
| The skill hook `plan-approved-check.py` blocks the main session's `Write`, and the plugin hook `scope-guard.py` blocks `Read /etc/hosts` inside `my-agent:explorer`. All 8 agents show at init, with `start: configured=sonnet` and `stop: actual=claude-sonnet-5-5` | live-t5c (2026-10-25, `-p` haiku, `--allowedTools Skill Agent Write Read Glob`) | stream `tool_result`: "…(G1b). Write outside the task folder", "scope-guard: Outside the read scope of explorer" | Real behavior of steps 2·3·4 confirmed |

## Manual procedures

### 7. G1·G3 popup notifications

1. Start an interactive session in `~/dev/labs/my-agent-sandbox/` with `claude --plugin-dir ~/dev/my-agent` (with the `claude-sessions` app running)
2. Ask "Show me any one question with AskUserQuestion"
3. With the popup open, wait 10 seconds and 70 seconds, and see whether a `claude-sessions` notification comes and which `notification_type` the `Notification` hook runs with (`.probe/Notification.jsonl`, after adding a `Notification` line to probe-hooks.json)
4. Write the result in row 7 of this table and in section 4.9. Even with no notification, the decision does not change (section 4.9)

### 9. Whether the status line cost includes subagents

1. In the same session, temporarily set the status line command to save the JSON it receives to a file (wrap `statusLine.command` with `tee`, in the practice project's `.claude/settings.json`)
2. Note `cost.total_cost_usd` before the subagent call
3. Call `my-agent:probe-worker` once, and note the value after it ends
4. Compare the difference with the run-log `stop:` line's `in`/`out`/`cw`/`cr` × the list prices in `l4-tools-guards/lib/prices.json`. If close, included; if near 0, not included
5. Write the result in section 4.8 and in row 9 of this table

### 6. Session end and background agents

1. In an interactive session, call `my-agent:probe-worker` with `run_in_background: true` and have it run `sleep 60; echo late`
2. End the session right away with `/exit`
3. After 1~2 minutes, check `finished` in the meta file, the time of the last transcript entry, and the run-log `stop:` line. If `late` is in the transcript, it kept running

## r11. data_dir setting reaches an installed plugin's skill (2026-10-29)

Run: `sh tests/probe/run-probes.sh r11` builds a one-skill plugin (`data-dir-skill/SKILL.md`) in a temp directory marketplace, installs it with `claude plugin install … --config data_dir=<folder>` under an isolated `CLAUDE_CONFIG_DIR`, then runs `/data-dir-probe:data-dir-probe`. A = the skill's frontmatter hook logs `CLAUDE_PLUGIN_OPTION_DATA_DIR` (`skill-data-dir.jsonl`); B = the Bash command the skill runs shows `BODY=[<folder>]` when `${user_config.data_dir}` is substituted.

- Result (person's run, logged-in isolated config, `R11_HOME=/tmp/r11 sh tests/probe/run-probes.sh r11`):
  - A (skill frontmatter hook env): **FAIL**. The `skill-data-dir.jsonl` record had `"argv": [""]` and `"CLAUDE_PLUGIN_OPTION_DATA_DIR": null`, so the env var is not set for skill frontmatter hooks.
  - B (SKILL.md body substitution): **PASS**. `BODY=[/tmp/r11/chosen-data-dir]`.
- A2 (plugin-level `hooks/hooks.json`, referenced from `plugin.json` like the real plugin; a PreToolUse command hook logs the env under `plugin-data-dir`): **PASS** (same run setup, 2026-10-29 00:44). The `plugin-data-dir.jsonl` record had `"argv": ["/tmp/r11/chosen-data-dir"]` and `"CLAUDE_PLUGIN_OPTION_DATA_DIR": "/tmp/r11/chosen-data-dir"`; in the same run A was again FAIL and B again PASS.
- So: plugin `hooks.json` hooks get the setting from the environment, skill frontmatter hooks do not, and the SKILL.md body gets it by substitution.
- A3 (skill frontmatter hook with `${user_config.data_dir}` as a command argument; event `skill-placeholder`): **FAIL** (same run setup, 2026-10-29 01:33). The record had `"argv": ["${user_config.data_dir}"]`, so the placeholder was passed through literally, not substituted. The `A3 hook installed: no` output line was a false negative: the plugin loads in place from the directory marketplace (`CLAUDE_PLUGIN_ROOT` was `/tmp/r11/mp/dd`, outside `$cfg`), so searching only `$cfg` could not find it. The check now also searches `$mp` and prints `yes` in this setup. The A3 record itself proves the new hook ran. In the A3 record `env.CLAUDE_CODE_SESSION_ID` equals `input.session_id` (`cd8066dc-8017-4f5e-842b-9a219a61a9d0`), the third session ID match.
- Conclusion: skill frontmatter hooks get neither the env var nor `${user_config.*}` substitution, so only plugin `hooks.json` hooks can read the setting (the SKILL.md body is substituted, but that is not a hook).

## Parallel coders in unit copies (261126)

Run record of `run4` (the latest of four runs, rerun after a `worktree.py` change; the evidence folder is `work/probe-copies/run4/` in the task folder `.my-agent/261126-parallel-coder-copies/`, kept with the task records, not in git). Result line of the script: `result: pass`.

### Method

- **Script and hook:** `sh tests/probe/copy-probe.sh <evidence folder>` (never run by the test suite) with the hook `tests/probe/copy-probe-hook.py`. One run starts two real `claude -p` sessions, one per location: a new temp folder that is a git repository (`git`, `/private/var/folders/…/T/tmp.x8W5LAIXty`) and a new plain temp folder (`nongit`, `…/tmp.9oe8mwXK79`). Each session creates two copies with `worktree.py create` (units `u1` and `u2`, task `261127-copy-probe`; the cd-guard line and `worktree:`/`base:` lines are in `create.txt`) and calls two `my-agent:coder` agents in one message, so a run has 4 coders. Claude Code 2.1.332, coder model `claude-sonnet-5-5` (the `stop:` lines).
- **Only the working copy judged:** `--plugin-dir` loads this working copy of the plugin and `--setting-sources project,local` leaves out the user settings that enable an installed my-agent plugin, so only this copy's hooks ran. The task's `Cd(...)` rule sits in the location's `.claude/settings.local.json`, written by `create` before the session started.
- **The three writes:** each coder makes its three `Write` calls as parallel calls in one message: (1) a file in its own copy, (2) a file in the main tree, (3) a file in the other coder's copy. The guard must allow (1) and deny (2) and (3). The coder prompt says that writes 2 and 3 are expected to be refused and that all three must still be made.
- **How a case is judged:** a write case passes only on an attempt and its effect. The hook log (`hook-log.jsonl`, one record per `Write` with `agent_id`, `first`, `unit`, `worktree`, `prompt_read`, `path`) must hold the attempt for that exact `path`. For (2) and (3) a guard deny line in `guard-lines.txt` (the run-log `guard:` lines, `decision=deny`, the denied path in `why`) must name that path and the file must not exist; for (1) the file must exist in the own copy (`files.txt`). A case with no attempt is `not attempted` and makes `result: fail`. The first-call case passes when the agent's first hook record (`"first": true`, whichever of its writes it is) read the unit and the `Worktree:` path (`"prompt_read": true`).
- **Earlier runs:** `run1` printed `result: pass` but was not valid evidence: the coders stopped after the main-tree refusal, the other-copy write was never attempted, and the script judged it by the file's absence. The script was changed to need an attempt plus a deny line. `run2` failed: one git coder (u1) again skipped its other-copy write. The script was changed to make the three writes as parallel calls in one message. `run3` passed with evidence: 6 write attempts and 4 guard denials per location. `worktree.py` was changed after that, so the probe was run again: `run4` passed with the same evidence (6 write attempts and 4 guard denials per location, `result: pass` in `run4/summary.txt`).
- **Spend cap and cost:** each session ran with `--max-budget-usd 2.00` (the script refuses to start without that flag, exit 2; at most 4.00 USD per run). Reported `total_cost_usd` of the sessions: `run4` git 0.34 and non-git 0.17 (0.51 USD in all); `run3` 0.36 USD, `run1` about 0.56 USD, `run2` about 0.39 USD.

### Evidence per location and coder

Evidence is the file and field in the run folder: `hook-log.jsonl` (`first`, `prompt_read`, `unit`, `worktree`, `path`), `guard-lines.txt` (`decision=deny`, `why=`) and `files.txt` (the files in the main tree and in each copy afterwards).

#### Location: git

| Coder | Case | Evidence (file · field) | Result |
|---|---|---|---|
| u1 | first call: unit read | `git/hook-log.jsonl`: record of agent `a36ea61ad6140bcc1` with `first: true`, `prompt_read: true`, `unit: u1`, `worktree` = copy u1, `tool: Write` | pass |
| u1 | own-copy write allowed | `git/hook-log.jsonl` attempt `…/my-agent-261127-copy-probe-u1/probe-u1.txt`; `git/files.txt` lists `probe-u1.txt` in copy u1; no deny line for that path | pass |
| u1 | main-tree write denied | attempt `probe-main-u1.txt`; `git/guard-lines.txt` deny `Outside the write scope of coder: …/probe-main-u1.txt`; not in the main tree of `git/files.txt` | pass (denied) |
| u1 | other-copy write denied | attempt `…/my-agent-261127-copy-probe-u2/probe-from-u1.txt`; deny line names that path; not in copy u2 of `git/files.txt` | pass (denied) |
| u2 | first call: unit read | `git/hook-log.jsonl`: agent `a3146f6aad6a5b157`, `first: true`, `prompt_read: true`, `unit: u2`, `worktree` = copy u2, `tool: Write` | pass |
| u2 | own-copy write allowed | attempt `…/my-agent-261127-copy-probe-u2/probe-u2.txt`; `git/files.txt` lists `probe-u2.txt` in copy u2 | pass |
| u2 | main-tree write denied | attempt `probe-main-u2.txt`; deny line names it; not in the main tree | pass (denied) |
| u2 | other-copy write denied | attempt `…/my-agent-261127-copy-probe-u1/probe-from-u2.txt`; deny line names it; not in copy u1 | pass (denied) |

#### Location: non-git

| Coder | Case | Evidence (file · field) | Result |
|---|---|---|---|
| u1 | first call: unit read | `nongit/hook-log.jsonl`: agent `a295f5b33882ab97c`, `first: true`, `prompt_read: true`, `unit: u1`, `worktree` = copy u1, `tool: Write` | pass |
| u1 | own-copy write allowed | attempt `…/my-agent-261127-copy-probe-u1/probe-u1.txt`; `nongit/files.txt` lists `probe-u1.txt` in copy u1 | pass |
| u1 | main-tree write denied | attempt `probe-main-u1.txt`; `nongit/guard-lines.txt` deny names it; not in the main tree | pass (denied) |
| u1 | other-copy write denied | attempt `…/my-agent-261127-copy-probe-u2/probe-from-u1.txt`; deny line names it; not in copy u2 | pass (denied) |
| u2 | first call: unit read | `nongit/hook-log.jsonl`: agent `aa6e293e5d6e4d71f`, `first: true`, `prompt_read: true`, `unit: u2`, `worktree` = copy u2, `tool: Write` | pass |
| u2 | own-copy write allowed | attempt `…/my-agent-261127-copy-probe-u2/probe-u2.txt`; `nongit/files.txt` lists `probe-u2.txt` in copy u2 | pass |
| u2 | main-tree write denied | attempt `probe-main-u2.txt`; deny line names it; not in the main tree | pass (denied) |
| u2 | other-copy write denied | attempt `…/my-agent-261127-copy-probe-u1/probe-from-u2.txt`; deny line names it; not in copy u1 | pass (denied) |

What the run shows about the guard's open questions (plan "To confirm"): the first user entry of a subagent's transcript was readable at its first `PreToolUse` call in both locations (`prompt_read: true` on every record, `first: true` on the first), so the fail-closed rows 1 and 3 did not fire. `PreToolUse` carries no transcript path (no such field in any hook-log record), so the prompt was read through the agent id lookup (`first_prompt`); the log does not record which of its two patterns matched. Every record's `cwd` was the session's folder, not the copy, so the guard does not depend on it. The non-git store-backed copies (`nongit/files.txt`: `copy-store/worktrees/my-agent-…-u1`, `…-u2`) were judged the same way as the git ones.

### Cd move

`Cd(...)` governs `/cd` and a host's move request, never a Bash `cd`. The probe's own `/cd` stream-json message (second user message) was not run as a command by `claude -p` in any run (`cd move: not driven`; the session answered that `/cd` is not available). So the observation below is not from the probe's `/cd`: it was typed by L1 in an interactive session, at the person's choice, not typed by the person.

| Location | Source | Observation | `cd move` |
|---|---|---|---|
| git | the probe's own `/cd` (`claude -p`, `run4/summary.txt`) | not run as a command | not driven |
| git | L1 typed `/cd <u1 copy>` in an interactive session via tmux (the person's choice): `claude` v2.1.332 started in the run4 git location, folder trusted at the prompt (`git/cd-move-observed.txt`, 2026-11-27) | `Can't move to …/my-agent-261127-copy-probe-u1 — it's excluded by the Cd(…/.claude/worktrees/**) rule in project local settings. Pick a directory outside that rule, or update it in /permissions` | refused |
| non-git | the probe's own `/cd` (`claude -p`, `run4/summary.txt`) | not run as a command | not driven |
| non-git | L1 typed `/cd <u1 copy>` in an interactive session via tmux (the person's choice): `claude` v2.1.332 started in the run4 non-git location, folder trusted at the prompt (`nongit/cd-move-observed.txt`, 2026-11-27) | the same refusal text, with the rule's own wording `excluded by the Cd(` | refused |

Both interactive sessions showed the startup warning `Deny rule Cd(…) matches no tool · check for typos`, while the rule still refused the move (the known warning, 4.6 "The startup warning is known and harmless"). The rule `Cd(/<resolved location>/.claude/worktrees/**)` matches the copy folder `my-agent-<task-id>-<unit>`, which the earlier `agent-*/**` pattern did not.

### Open risks

- **A new settings file read only from the next session:** in the probe `create` wrote `<location>/.claude/settings.local.json` before the session started, so the rule applied from the first move. A first `create` in a session that runs now writes a file that Claude Code may read only in sessions started after it (the `added` line says so: `new file: Claude Code may read it only in sessions started after this`). The probe did not test a file created mid-session, so a move in that session may not be refused. The session folder check in 3A (dev profile) stays as the second line of defence.
- **A coder group run in a workflow** was not probed: where a workflow `agent()` coder's transcript lies, and whether the guard finds it, is not confirmed. If it cannot be read, the guard refuses that coder's writes while copies run (fail closed).
- **A host's move request** (`set_cwd`) was not probed, only the typed `/cd`.
