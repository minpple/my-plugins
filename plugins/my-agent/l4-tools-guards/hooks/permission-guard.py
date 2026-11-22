#!/usr/bin/env python3
"""Plugin hook (hooks.json, PreToolUse: Bash, Read, Grep, Glob and MCP tools): apply the `ask` and `deny` rules of
`permissions/permissions.json` while a task is active (architecture 4.4 "Permission guard").

A plugin cannot ship permission rules, and rules merged into the user settings would act in every session. This hook
reads the list and gives the verdict itself, so the rules act only during a my-agent task: for a call of the session
that owns the active task, the main thread and its subagents. No task, a broken `.active` and another session's call
give no output.

Rules, in the permission rule syntax (a rule in any other form is an error):
- `Bash(<text>:*)`: a simple command that is `<text>` or starts with `<text>` and a space.
- `Bash(<text with *>)`: `*` is any text; a trailing ` *` also matches the bare end when it is the only wildcard.
  Both forms are compared with every simple command of the line as `ma_bash.command_texts` gives it.
- `Read(//<path>)` (from the file system root) and `Read(~/<path>)` (from home): `**` crosses folders, `*` stays in
  one name; compared without case with the path as written and as resolved. It covers the `file_path` of Read, the
  `path` of Grep and Glob, and every path `ma_bash.read_paths` names in a Bash command (a read it cannot name gives no
  verdict).
- a bare tool name (an MCP tool): that tool.

Verdicts: a `deny` rule is a deny and wins over any ask; an `ask` rule is a G2 ask. With `permission_mode`
`bypassPermissions` an ask becomes a deny (Claude Code may run a hook ask there without a prompt).

It acts on Claude Code only: on Codex and Antigravity it prints nothing and exits 0. Any error → exit 2 with
`permission-guard: <Type>: <message>`, so the call is blocked.
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import ma_active  # noqa: E402
import ma_bash  # noqa: E402
import ma_host  # noqa: E402

RULES = Path(__file__).resolve().parents[1] / 'permissions' / 'permissions.json'
PATH_TOOLS = {'Read': 'file_path', 'Grep': 'path', 'Glob': 'path'}
TEXT_MAX = 200

DENY = 'my-agent permission rules: `{rule}` denies {what}; not allowed during a my-agent task'
ASK = 'my-agent permission rules: `{rule}` asks before {what} (G2)'
BYPASS = ('my-agent permission rules: `{rule}` asks before {what}; the bypassPermissions mode may run an ask without '
          'the G2 dialog, so it is denied')


def load(path: Path = RULES) -> dict:
    """{'ask': [...], 'deny': [...]} from permissions.json."""
    perms = json.loads(path.read_text(encoding='utf-8'))['permissions']
    return {kind: list(perms.get(kind, [])) for kind in ('ask', 'deny')}


def split(rule: str) -> tuple:
    """(tool, pattern) of a rule; the pattern is None for a bare tool name."""
    m = re.fullmatch(r'(\w+)\((.+)\)', rule, re.S)
    if m:
        if m.group(1) not in ('Bash', 'Read'):
            raise ValueError(f'unknown rule form: {rule}')
        return m.group(1), m.group(2)
    if not re.fullmatch(r'\w+', rule):
        raise ValueError(f'unknown rule form: {rule}')
    return rule, None


def bash_match(pattern: str, text: str) -> bool:
    if pattern.endswith(':*'):
        head = pattern[:-2]
        return text == head or text.startswith(head + ' ')
    if re.fullmatch('.*'.join(re.escape(part) for part in pattern.split('*')), text, re.S):
        return True
    return pattern.endswith(' *') and pattern.count('*') == 1 and text == pattern[:-2]


def read_regex(pattern: str):
    if pattern.startswith('//'):
        pattern = pattern[1:]
    elif pattern.startswith('~/'):
        pattern = str(Path.home()) + pattern[1:]
    else:
        raise ValueError(f'a Read rule must start with // or ~/: {pattern}')
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith('**/', i):
            out.append('(?:.*/)?')
            i += 3
        elif pattern.startswith('**', i):
            out.append('.*')
            i += 2
        elif pattern[i] == '*':
            out.append('[^/]*')
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile(''.join(out), re.I | re.S)


def forms(raw: str, cwd: Path) -> list:
    """The spellings of one path a Read rule is compared with: as written (made absolute) and resolved; each also with
    a trailing `/`, so a folder given to Grep, Glob or a command matches a `<folder>/**` rule."""
    p = Path(os.path.expanduser(raw))
    p = p if p.is_absolute() else cwd / p
    out = [os.path.normpath(str(p))]
    try:
        out.append(str(p.resolve()))
    except (OSError, RuntimeError):
        pass
    return [f + tail for f in dict.fromkeys(out) for tail in ('', '/')]


def targets(inp: dict, cwd: Path) -> tuple:
    """(command texts, read paths) of the call."""
    tool = inp.get('tool_name')
    ti = inp.get('tool_input') if isinstance(inp.get('tool_input'), dict) else {}
    if tool == 'Bash':
        cmd = ti.get('command')
        if not isinstance(cmd, str) or not cmd.strip():
            return [], []
        return ma_bash.command_texts(cmd), [str(p) for p in ma_bash.read_paths(cmd, cwd) or []]
    raw = ti.get(PATH_TOOLS.get(tool, ''))
    return [], [raw] if isinstance(raw, str) and raw else []


def hit(rule: str, tool, texts: list, paths: list, cwd: Path):
    """What `rule` matches in the call (a short text for the reason), or None."""
    name, pattern = split(rule)
    if pattern is None:
        return f'the tool `{tool}`' if name == tool else None
    if name == 'Bash':
        for text in texts:
            if bash_match(pattern, text):
                return '`' + (text if len(text) <= TEXT_MAX else text[:TEXT_MAX - 1] + '…') + '`'
        return None
    rx = read_regex(pattern)
    for raw in paths:
        if any(rx.fullmatch(f) for f in forms(raw, cwd)):
            return f'a read of `{raw}`'
    return None


def output(decision: str, reason: str) -> dict:
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': decision,
                                   'permissionDecisionReason': reason}}


def judge(inp: dict, rules: dict = None):
    """Hook output (deny or ask) for one Claude Code input, or None to let the call through."""
    cwd = inp.get('cwd') or os.getcwd()
    active = ma_active.find_active(cwd)
    if active is None or not ma_active.owns(active, inp):
        return None
    rules = load() if rules is None else rules
    cwd = Path(cwd)
    tool = inp.get('tool_name')
    texts, paths = targets(inp, cwd)
    for rule in rules['deny']:
        what = hit(rule, tool, texts, paths, cwd)
        if what:
            return output('deny', DENY.format(rule=rule, what=what))
    for rule in rules['ask']:
        what = hit(rule, tool, texts, paths, cwd)
        if what:
            if inp.get('permission_mode') == 'bypassPermissions':
                return output('deny', BYPASS.format(rule=rule, what=what))
            return output('ask', ASK.format(rule=rule, what=what))
    return None


def main() -> int:
    try:
        inp = json.loads(sys.stdin.read() or '{}')
        if not isinstance(inp, dict):
            raise ValueError('hook input is not an object')
        if ma_host.hook_host(inp) != 'claude':
            return 0
        out = judge(inp)
        if out:
            print(json.dumps(out, ensure_ascii=False))
        return 0
    except Exception as e:   # block the call: exit 2 is a blocking error for PreToolUse
        print(f'permission-guard: {type(e).__name__}: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
