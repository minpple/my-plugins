#!/usr/bin/env python3
"""Plugin hook (hooks.json, PreToolUse: Bash): judge `git push` and `git commit` forms from the parsed command
(architecture 4.4 "Git guard").

The pattern deny rules match text and act on Claude Code only after a hand merge. This hook reads the command as the
`ma_bash` tokenizer does (`git_forms`: prefix words, git global options, `sh -c` bodies, command substitutions), so a
real form is stopped on every host and a plain mention of it passes.

It gives a verdict only while a task is active and only for a call of the session that owns it, the main thread and its
subagents (unlike the other gate hooks, a call with `agent_id` is judged here). No task, a broken `.active`, another
session's call, an empty command, a command with no git and a command with no form give no output.

Verdicts: a deny form (force push in any position or cluster, a `+` refspec, `--mirror`, the forms that delete remote
refs, `commit -n`, the long hook-skipping option, a hooks-path override) is a deny; the first deny wins over any ask.
`--force-with-lease` alone, a substitution in an option, refspec or pathspec slot, and a push or commit that does not
tokenize and shows no form are a G2 ask. An ask with nobody to answer it becomes a deny: from a subagent call (workers
never push or commit; the main thread of a session started with `--agent` counts), and with `permission_mode`
`bypassPermissions` (Claude Code may run a hook ask there without a prompt). Other modes keep the verdict.

Hosts go through `ma_host`: Claude Code gets the hook JSON; Codex gets the deny JSON with exit 0 and an ask as exit 2 with
a G2 `ask` run-log line (one `answer gate=G2` line releases one call); Antigravity gets `deny` or `force_ask`. Parsing
first leaves the Codex hook-health mark on every Bash call. Any error → exit 2 with `git-guard: <Type>: <message>`.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import ma_active  # noqa: E402
import ma_bash  # noqa: E402
import ma_host  # noqa: E402

DENY = 'my-agent git guard: {form} in `{text}`; not allowed during a my-agent task'
ASK = 'my-agent git guard: {form} in `{text}`; allow it only if this is your own request, not the task\'s'
SUBAGENT = 'my-agent git guard: {form} in `{text}`; my-agent workers do not push or commit, so it is denied: report it to L1'
BYPASS = ('my-agent git guard: {form} in `{text}`; the bypassPermissions mode may run an ask without the G2 dialog, '
          'so it is denied')


def output(decision: str, reason: str) -> dict:
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': decision,
                                   'permissionDecisionReason': reason}}


def judge(inp):
    """Hook output (deny or ask) for one Claude-shaped input, or None to let the call through."""
    if not isinstance(inp, dict):
        raise ValueError('hook input is not an object')
    ti = inp.get('tool_input') if isinstance(inp.get('tool_input'), dict) else {}
    if inp.get('tool_name') != 'Bash':
        return None
    cmd = ti.get('command')
    if not isinstance(cmd, str):
        raise ValueError('Bash input has no command text')
    if not cmd.strip():
        return None
    active = ma_active.find_active(inp.get('cwd') or os.getcwd())
    if active is None or not ma_active.owns(active, inp):
        return None
    forms = ma_bash.git_forms(cmd)
    for f in forms:
        if f.verdict == 'deny':
            return output('deny', DENY.format(form=f.form, text=f.text))
    for f in forms:
        if f.verdict == 'ask':
            if ma_active.in_subagent(inp):
                return output('deny', SUBAGENT.format(form=f.form, text=f.text))
            if inp.get('permission_mode') == 'bypassPermissions':
                return output('deny', BYPASS.format(form=f.form, text=f.text))
            return output('ask', ASK.format(form=f.form, text=f.text))
    return None


def main() -> int:
    try:
        call = ma_host.parse(sys.stdin.read())
        out = None
        for inp in call.inps:
            out = ma_host.stronger(out, judge(inp))
            if ma_host.decision(out) == 'deny':
                break
        return ma_host.emit(call, out)
    except Exception as e:   # block the call: exit 2 is a blocking error for PreToolUse
        print(f'git-guard: {type(e).__name__}: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
