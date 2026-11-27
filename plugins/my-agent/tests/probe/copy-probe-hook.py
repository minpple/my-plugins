#!/usr/bin/env python3
"""Probe-only PreToolUse hook of copy-probe.sh (passed with `--settings`; it never decides anything).

For each tool call made inside a subagent (the hook input has `agent_id`) it appends one JSON line to
`$COPY_PROBE_LOG`: `agent_id`, `agent_type`, `session_id`, `cwd`, `tool`, `first` (true for the agent's first
tool call), and `unit` and `worktree` as the guard reads them from the agent's first prompt at this moment
(`ma_subagent.first_prompt`, with the same 2 s wait; the prompt's first line `Work unit: u<n>` and its second line
`Worktree: <path>`), `path` (the call's `file_path`, null when it has none), plus `prompt_read` (false when the transcript could not be read yet). Always exits 0.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'l4-tools-guards' / 'lib'))


def lines_of(prompt):
    return (prompt or '').splitlines()


def unit_and_worktree(prompt):
    """(unit, worktree) from the prompt's first line and its second line; None for a line that is not there."""
    lines = lines_of(prompt)
    unit = worktree = None
    if lines:
        m = re.match(r'\s*Work unit:\s*(u\d+)\b', lines[0])
        unit = m.group(1) if m else None
    if len(lines) > 1:
        m = re.match(r'\s*Worktree:\s*(\S.*?)\s*$', lines[1])
        worktree = m.group(1) if m else None
    return unit, worktree


def path_of(inp):
    """The file path a Write/Edit call names (`tool_input.file_path`), else None."""
    ti = inp.get('tool_input')
    p = ti.get('file_path') if isinstance(ti, dict) else None
    return p if isinstance(p, str) else None


def first_call(log, agent_id):
    """True exactly once per agent id (an exclusive marker file next to the log, safe for parallel agents)."""
    marker = Path(log).with_name('first-' + re.sub(r'[^A-Za-z0-9_.-]', '_', agent_id))
    try:
        os.close(os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        return True
    except OSError:
        return False


def main():
    try:
        inp = json.loads(sys.stdin.read())
        log = os.environ.get('COPY_PROBE_LOG')
        agent_id = inp.get('agent_id') if isinstance(inp, dict) else None
        if not (log and isinstance(agent_id, str) and agent_id):
            return 0
        import ma_subagent
        prompt = ma_subagent.first_prompt(agent_id, inp.get('session_id'), wait=True)
        unit, worktree = unit_and_worktree(prompt)
        rec = {'agent_id': agent_id, 'agent_type': inp.get('agent_type'), 'session_id': inp.get('session_id'),
               'cwd': inp.get('cwd'), 'tool': inp.get('tool_name'), 'first': first_call(log, agent_id),
               'prompt_read': prompt is not None, 'unit': unit, 'worktree': worktree, 'path': path_of(inp)}
        with open(log, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, sort_keys=True) + '\n')
    except BaseException:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
