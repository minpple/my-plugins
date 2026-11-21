# my-agent on Antigravity

When running the `my-agent` skill in Antigravity:

- Before the first question or command, read `l1-orchestration/hosts-antigravity.md` in the plugin folder (two levels above `skills/my-agent/SKILL.md`, or the path given on the `SessionStart` line) and use the Antigravity tool and role names it defines.
- Ask the person through `ask_question`, never in plain prose when a popup is required.
- Use `invoke_subagent` with `TypeName` `my-agent-<role>` for L2/L3 delegation.
