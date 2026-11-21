#!/usr/bin/env python3
"""Generate the Antigravity forms of the ten agents, the Antigravity manifest and root hooks.json from the Claude sources.

usage: build-antigravity.py --write | --check | --install-agents | --check-agents
                            [--root DIR] [--agy-home DIR]

Sources: the agent `.md` files listed in `.claude-plugin/plugin.json` and that file itself. Outputs, under the plugin
root: `antigravity/agents/my-agent-<role>.md` (one per agent), `.antigravity-plugin/plugin.json` and `hooks.json`.

Each generated agent `.md` keeps valid YAML frontmatter (`name`, `description`, `model: inherit`, `subagent: true`,
and `tools` mapped from Claude tool names to Antigravity tool names) followed by the `.md` body verbatim. The manifest
copies name, version, description and author, plus homepage and repository. `hooks.json` at the plugin root registers
the my-agent hooks in Antigravity's format (`PreToolUse`, `PostToolUse`, `SessionStart`).

`--check` exits 1 and prints each file that differs or is missing, and each `antigravity/agents/*.md` the build does
not produce; `--write` rewrites the files and removes those extra agent files. Exit 2 for bad arguments.

`--install-agents` copies the ten `antigravity/agents/*.md` into `<agy home>/agents/` (`--agy-home`, else
`$AGY_CONFIG_HOME`, else `~/.gemini/config`), because keeping a root `agents/` folder inside the shared plugin would
duplicate the agents in Claude Code. A version marker comment (`<!-- my-agent <version> (build-antigravity.py
--install-agents) -->`) is placed on the first line after the closing `---` at copy time; repository files stay
comment-free. Any same-named file without that marker (or a link or folder) is left untouched (`skipped:`).
`--check-agents` prints the same states without writing. Both end with `Antigravity agents: <form>`; exit 0 only when
nothing was skipped (install) or all ten are up to date (check).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[2]
MARKER_RE = re.compile(r'^<!-- my-agent (\S+) \(build-antigravity\.py --install-agents\) -->$')
MANIFEST_KEYS = ('name', 'version', 'description', 'author')
HOMEPAGE = 'https://minpple.github.io/my-plugins/'
REPOSITORY = 'https://github.com/minpple/my-plugins'

TOOL_MAP = {
    'Read': ('read_file',),
    'Edit': ('edit_file',),
    'Write': ('write_file',),
    'Bash': ('run_command',),
    'Grep': ('grep_search',),
    'Glob': ('find_by_name',),
    'WebSearch': ('search_web',),
    'WebFetch': ('search_web',),
}

ANTIGRAVITY_HOOKS = {
    'my-agent': {
        'PreToolUse': [
            {
                'matcher': '*',
                'hooks': [
                    {
                        'type': 'command',
                        'command': 'python3 l4-tools-guards/hooks/scope-guard.py',
                        'timeout': 30,
                    }
                ],
            },
            {
                'matcher': 'invoke_subagent',
                'hooks': [
                    {
                        'type': 'command',
                        'command': 'python3 l4-tools-guards/hooks/subagent-log.py call',
                        'timeout': 10,
                    }
                ],
            },
            {
                'matcher': 'invoke_subagent|run_workflow|edit_file|replace_file_content|multi_replace_file_content|write_file|write_to_file|run_command',
                'hooks': [
                    {
                        'type': 'command',
                        'command': 'python3 l4-tools-guards/hooks/plan-approved-check.py',
                        'timeout': 30,
                    }
                ],
            },
            {
                'matcher': 'run_command|edit_file|replace_file_content|multi_replace_file_content|write_file|write_to_file',
                'hooks': [
                    {
                        'type': 'command',
                        'command': 'python3 l4-tools-guards/hooks/verdict-fresh-check.py',
                        'timeout': 30,
                    }
                ],
            },
        ],
        'PostToolUse': [
            {
                'matcher': '*',
                'hooks': [
                    {
                        'type': 'command',
                        'command': 'python3 l4-tools-guards/hooks/permission-log.py answer',
                        'timeout': 10,
                    }
                ],
            }
        ],
        'SessionStart': [
            {
                'type': 'command',
                'command': 'python3 l4-tools-guards/hooks/session-notice.py',
                'timeout': 10,
            }
        ],
    }
}


def split_md(text: str):
    """(frontmatter dict, body) of an agent `.md`; the body starts after the closing `---` line."""
    head, body = text.split('\n---\n', 1)
    meta = {}
    for line in head.splitlines()[1:]:
        key, _, val = line.partition(':')
        meta[key.strip()] = val.strip()
    return meta, body


def yaml_str(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        s = s[1:-1]
    return json.dumps(s, ensure_ascii=False)


def agy_name(meta: dict) -> str:
    return 'my-agent-' + meta['name']


def map_tools(raw: str) -> list:
    out = []
    for item in (x.strip() for x in raw.split(',') if x.strip()):
        for mapped in TOOL_MAP.get(item, ()):
            if mapped not in out:
                out.append(mapped)
    return out


def agent_md(meta: dict, body: str) -> str:
    name = agy_name(meta)
    tools = map_tools(meta.get('tools', ''))
    lines = [
        '---',
        f'name: {name}',
        f'description: {yaml_str(meta["description"])}',
        'model: inherit',
        'subagent: true',
    ]
    if tools:
        lines.append('tools:')
        for tool in tools:
            lines.append(f'  - {tool}')
    lines.append('---')
    return '\n'.join(lines) + '\n' + body


AGY_RULES_MD = """# my-agent on Antigravity

When running the `my-agent` skill in Antigravity:

- Before the first question or command, read `l1-orchestration/hosts-antigravity.md` in the plugin folder (two levels above `skills/my-agent/SKILL.md`, or the path given on the `SessionStart` line) and use the Antigravity tool and role names it defines.
- Ask the person through `ask_question`, never in plain prose when a popup is required.
- Use `invoke_subagent` with `TypeName` `my-agent-<role>` for L2/L3 delegation.
"""


def build(root: Path) -> dict:
    """{relative path: text} of every generated Antigravity file."""
    plugin = json.loads((root / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))
    out = {}
    for ref in plugin['agents']:
        meta, body = split_md((root / ref).read_text(encoding='utf-8'))
        name = agy_name(meta)
        out[f'antigravity/agents/{name}.md'] = agent_md(meta, body)
    manifest = {k: plugin[k] for k in MANIFEST_KEYS}
    manifest['homepage'] = HOMEPAGE
    manifest['repository'] = REPOSITORY
    out['.antigravity-plugin/plugin.json'] = json.dumps(manifest, indent=2, ensure_ascii=False) + '\n'
    out['hooks.json'] = json.dumps(ANTIGRAVITY_HOOKS, indent=2, ensure_ascii=False) + '\n'
    out['rules/AGENTS.md'] = AGY_RULES_MD
    return out


def marker_line(version: str) -> str:
    return f'<!-- my-agent {version} (build-antigravity.py --install-agents) -->'


def with_marker(text: str, version: str) -> str:
    head, body = text.split('\n---\n', 1)
    return f'{head}\n---\n{marker_line(version)}\n{body}'


def file_state(target: Path, text: str, version: str) -> str:
    """'missing', 'ok', 'stale:<old version>', 'stale:changed' or 'skipped' for one installed file."""
    if target.is_symlink():
        return 'skipped'
    if not target.exists():
        return 'missing'
    if not target.is_file():
        return 'skipped'
    try:
        raw = target.read_bytes().decode('utf-8')
    except UnicodeDecodeError:
        return 'skipped'
    if '\n---\n' not in raw:
        return 'skipped'
    head, after = raw.split('\n---\n', 1)
    line1, _, rest = after.partition('\n')
    m = MARKER_RE.match(line1)
    if not m:
        return 'skipped'
    if m.group(1) != version:
        return 'stale:' + m.group(1)
    reconstructed = f'{head}\n---\n{rest}'
    return 'ok' if reconstructed == text else 'stale:changed'


def summary(states: list, version: str) -> str:
    """The `Antigravity agents:` form for the states of the ten files."""
    ok = states.count('ok')
    skipped = states.count('skipped')
    if skipped:
        return f'{ok} of {len(states)} installed ({version}); {skipped} skipped'
    stale = []
    for s in states:
        if s.startswith('stale:') and s[6:] not in stale:
            stale.append(s[6:])
    if stale:
        return f'stale ({", ".join(stale)})'
    if ok == len(states):
        return f'installed {len(states)} ({version})'
    if ok == 0:
        return 'not installed'
    return f'{ok} of {len(states)} installed ({version})'


def agents_mode(root: Path, home: Path, install: bool) -> int:
    files = build(root)
    version = json.loads((root / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))['version']
    sources = {}
    for rel, text in files.items():
        if rel.startswith('antigravity/agents/'):
            p = root / rel
            if not p.is_file() or p.read_text(encoding='utf-8') != text:
                print('build-antigravity: generated files differ; run --write first')
                return 1
            sources[rel.rsplit('/', 1)[1]] = text
    folder = home / 'agents'
    if os.path.lexists(folder) and not folder.is_dir():
        print(f'build-antigravity: {folder} is not a folder; nothing installed')
        print('Antigravity agents: not installed')
        return 1
    if install:
        folder.mkdir(parents=True, exist_ok=True)
    states = []
    for name, text in sources.items():
        target = folder / name
        state = file_state(target, text, version)
        if install and state != 'skipped':
            if state == 'ok':
                print(f'up to date: {name}')
            else:
                target.write_text(with_marker(text, version), encoding='utf-8')
                was = f' (was {state[6:]})' if state != 'missing' else ''
                print(f'installed: {name}{was}')
                state = 'ok'
        elif state == 'skipped':
            print(f'skipped: not generated by my-agent: {name}')
        elif state == 'missing':
            print(f'missing: {name}')
        elif state.startswith('stale:'):
            print(f'stale: {name} ({state[6:]})')
        else:
            print(f'up to date: {name}')
        states.append(state)
    print(f'Antigravity agents: {summary(states, version)}')
    if install:
        return 1 if 'skipped' in states else 0
    return 0 if all(s == 'ok' for s in states) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--write', action='store_true')
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--install-agents', action='store_true')
    mode.add_argument('--check-agents', action='store_true')
    ap.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    ap.add_argument('--agy-home', type=Path, default=None)
    args = ap.parse_args(argv)
    root = args.root
    if args.install_agents or args.check_agents:
        home = args.agy_home or Path(os.environ.get('AGY_CONFIG_HOME') or '~/.gemini/config').expanduser()
        return agents_mode(root, home, args.install_agents)
    files = build(root)
    if args.write:
        for rel, text in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding='utf-8')
        agents = root / 'antigravity' / 'agents'
        if agents.is_dir():
            for p in sorted(agents.glob('*.md')):
                if f'antigravity/agents/{p.name}' not in files:
                    p.unlink()
        return 0
    bad = [rel for rel, text in files.items()
           if not (root / rel).is_file() or (root / rel).read_text(encoding='utf-8') != text]
    agents = root / 'antigravity' / 'agents'
    if agents.is_dir():
        bad += [f'antigravity/agents/{p.name}' for p in sorted(agents.glob('*.md'))
                if f'antigravity/agents/{p.name}' not in files]
    for rel in bad:
        print(f'build-antigravity: differs: {rel}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
