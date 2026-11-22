# Host mapping (Antigravity)

The phase, profile and agent files use Claude Code names. In an Antigravity session, read each name below as the Antigravity name beside it. A row that says `not available in Antigravity` has no Antigravity counterpart: follow its note, or skip the step that needs it and say so in one chat line.

| Claude Code | Antigravity | Note |
|---|---|---|
| `AskUserQuestion` popup | `ask_question` | Pass the question and its options (`question`, `options`, `is_multi_select`), with the recommended option first prefixed `(Recommended)`. Write the `ask` and `answer` lines as usual. Never ask in plain prose when a popup is required. |
| `Agent` (start a subagent) | `invoke_subagent` | Input fields: `TypeName`, `Role`, `Prompt`, `Model`, `Workspace`. Subagents run asynchronously and send a message back when done; stop calling tools to wait reactively rather than polling. |
| `subagent_type` `my-agent:<role>` | `TypeName` `my-agent-<role>` | Installed into `~/.gemini/config/agents/` by `build-antigravity.py --install-agents` so `invoke_subagent` recognizes each my-agent role without duplicating agents in Claude Code. New agents appear from the next Antigravity session. |
| Intake item 9 (Monitor) | item 9, then the Antigravity agents check | After the monitor line, run `python3 <plugin folder>/l4-tools-guards/scripts/build-antigravity.py --check-agents` and carry its last line into the Intake report. When that line is not `Antigravity agents: installed 10 (<version>)`, show the output and popup `Install (Recommended)` / `Skip` (never answered by L1, also under delegated approval; recorded after the create call as `run-log.py` ask/answer lines). `Install` runs `build-antigravity.py --install-agents`, shows any `skipped:` line, and adds its last line and `New agents show in a new Antigravity session.` to the report. The report may take these lines beyond its 7-line limit. |
| `isolation: "worktree"` | `Workspace: "share"` | Antigravity's `share` workspace creates an isolated working copy sharing the parent repository (like a git worktree). Use `"inherit"` for non-isolated roles. |
| `run_in_background` | built-in | `invoke_subagent` always runs in the background and notifies the parent reactively. |
| `model`, `effort` call arguments | `Model` (`inherit`, `pro`, `flash`, `flash_lite`) | `agent-models.py` reads the `antigravity` section of `agent-models.json`. Pass `Model` only when `pass=` lists `model`; `effort` has no per-call argument on `invoke_subagent`. An inline role (`pass=inline`) runs in the main session as usual. |
| `maxTurns` of an agent definition | not available in Antigravity | Not supported in Antigravity agent frontmatter. |
| `Workflow` | `run_workflow` | Blocked by `plan-approved-check.py` before G1b approval. |
| `SendMessage` | `send_message` | Uses the subagent's `conversationId` returned by `invoke_subagent`. |
| Subagent hand-back (its final message) | message delivered reactively from the subagent | Stop calling tools after launching subagents; Antigravity resumes the session when each subagent replies. |
| `Bash` | `run_command` | Pass `CommandLine`, `WaitMsBeforeAsync`, and `toolSummary`. |
| `Edit` | `edit_file` | Uses `Path`, `Target`, and `Replacement`. |
| `Write` | `write_file` | Uses `Path`, `Content`, and `Overwrite: true` when replacing an existing file. |
| `Read` | `read_file` | Uses `Path`, optional `StartLine` / `EndLine`. |
| `Grep` | `grep_search` | Or search via `run_command` when `grep_search` is unavailable in the session. |
| `Glob` | `find_by_name` | Or list paths via `run_command` when `find_by_name` is unavailable in the session. |
| `WebSearch` | `search_web` | Available to L1, researcher and verifier. |
| `WebFetch` | `search_web` / `read_url_content` | Use `read_url_content` when available, else `search_web`. |
| `${CLAUDE_PLUGIN_ROOT}` in skill text | the plugin folder of the session line | Antigravity passes the text literally, not expanded. Read it as the plugin folder named on the `SessionStart` line `my-agent on Antigravity: plugin folder <path> …`. When absent, the plugin folder is two levels above `skills/my-agent/SKILL.md`. Hooks receive `$PLUGIN_ROOT` and run with the plugin folder as working directory. |
| `$CLAUDE_CODE_SESSION_ID` | `$ANTIGRAVITY_CONVERSATION_ID` | Also printed on the `SessionStart` line (`session <id>`). `ma_host.session_id()` reads `$ANTIGRAVITY_CONVERSATION_ID` automatically. |
| `${user_config.data_dir}`, `${user_config.task_dir}` | the data and task folders of the session line | Antigravity passes the text literally, not expanded. Read them from the `SessionStart` line; without it, `data-dir.py` returns `$MA_TASKS_DIR` (or `~/.my-agent-data`) and `$MA_TASK_DIR` (or `.my-agent`). |
| G2 permission dialog | Antigravity `force_ask` prompt | Gate hooks (`plan-approved-check.py`, `verdict-fresh-check.py`, `git-guard.py`) emit `{"decision": "force_ask", "reason": "..."}` so Antigravity prompts the person for one-time approval, ignoring cached permissions. |
| `/my-agent` | the skill `my-agent` | Discovered from `skills/my-agent/SKILL.md`. |
| `/my-agent:monitor` | the skill `monitor` | Discovered from `skills/monitor/SKILL.md`. |
| Subagent start/stop hooks (`SubagentStart`, `SubagentStop`) | not available in Antigravity | Antigravity's hook lifecycle covers `SessionStart`, `PreToolUse`, `PostToolUse`, `PreInvocation`, `PostInvocation` and `Stop`. `subagent-log.py call` records each `invoke_subagent` call on `PreToolUse`; `start:` and `stop:` lines are not emitted automatically. |
| `PermissionRequest` hook | not available in Antigravity | `permission-log.py ask` has no Antigravity lifecycle event; G2 prompts are handled natively by `force_ask`. |
