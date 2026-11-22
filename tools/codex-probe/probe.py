#!/usr/bin/env python3
"""Codex install probe (repository tool, not shipped with a plugin).

Subcommands:
  snapshot --out <folder> [--skills <folder>] [--cache <marketplace>/<plugin>]
                              save the output of read-only Codex commands; --skills runs `codex debug prompt-input` there and adds
                              skills-list.txt, skills-source.txt and skills-evidence.txt;
                              --cache adds cache-files.txt and the .codex-plugin/plugin.json copies
  check install <folder> [--root <path>] [--version <v>]
                              exit 0 when the saved snapshot proves my-agent is installed from the new copy

The Codex binary comes from the global `--codex <path>` option (default `codex`).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# ---- snapshot ----

def call(codex: str, argv: list, cwd=None, env=None):
    return subprocess.run([codex] + argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=900)


def codex_home(args) -> Path:
    return Path(args.codex_home or os.environ.get('CODEX_HOME') or '~/.codex').expanduser()


def snapshot_skills(args, out: Path):
    """skills-list/-source/-evidence from `codex debug prompt-input` (the hard source); the raw output is not kept."""
    folder = Path(args.skills)
    done = call(args.codex, ['debug', 'prompt-input', SKILLS_INPUT_PROMPT], cwd=str(folder))
    home = codex_home(args)
    parts = (args.cache or 'my-plugins/my-agent').split('/')
    descs = my_agent_descriptions(home, *(parts if len(parts) == 2 and all(parts) else ['my-plugins', 'my-agent']))
    skills = {'root': descs['root'], 'monitor': descs['monitor']}
    names, lines, total = [], [], 0
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'prompt-input.txt'
        path.write_text(done.stdout, encoding='utf-8')
        entries = all_entries(path)
        total = len(entries)
        matched = [e for e in entries if any(description_matches(e['description'], d) for ds in skills.values() for d in ds)]
        for e in distinct_entries(matched):
            shown = 'unresolved' if e['path'] == 'unresolved' else scrub_text(e['path'], home)
            names.append(e['name'])
            lines.append(f'prompt-input:{e["at"]}  - {e["name"]}: '
                         f'{scrub_text(re.sub(chr(92) + "s+", " ", e["description"]).strip(), home)} (file: {shown})')
    if not lines:
        lines = [f'no listing entry of my-agent was found ({total} listing entries in all)']
    (out / 'skills-list.txt').write_text(''.join(n + '\n' for n in names), encoding='utf-8')
    (out / 'skills-source.txt').write_text(('prompt-input' if total else 'none') + '\n', encoding='utf-8')
    (out / 'skills-evidence.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def cmd_snapshot(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    steps = [('codex-version.txt', ['--version']), ('plugin-list.txt', ['plugin', 'list']),
             ('marketplace-list.txt', ['plugin', 'marketplace', 'list'])]
    for name, argv in steps:
        done = call(args.codex, argv)
        (out / name).write_text(done.stdout + (f'\n[stderr]\n{done.stderr}' if done.stderr else ''), encoding='utf-8')
    if args.skills:
        snapshot_skills(args, out)
    if args.cache:
        parts = args.cache.split('/')
        if len(parts) != 2 or not all(parts):
            sys.exit('--cache takes <marketplace>/<plugin>')
        base = codex_home(args) / 'plugins' / 'cache' / parts[0] / parts[1]
        files = sorted(str(p.relative_to(base)) for p in base.rglob('*') if p.is_file()) if base.is_dir() else []
        (out / 'cache-files.txt').write_text('\n'.join(files), encoding='utf-8')
        for manifest in sorted(base.glob('*/.codex-plugin/plugin.json')):
            dest = out / 'cache' / manifest.parent.parent.name / 'codex-plugin.json'
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(manifest, dest)
    return 0


def walk(value):
    yield value
    if isinstance(value, dict):
        for v in value.values():
            yield from walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from walk(v)


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def cmd_check(args) -> int:
    return check_install(args)


def parse_plugin_list(text: str):
    """(marketplace root, status, version) of the my-agent@my-plugins row, or None."""
    path = None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith('Marketplace `'):
            path = next((l.strip() for l in lines[i + 1:] if l.strip()), '')
        m = re.match(r'^my-agent@my-plugins\s+(installed, enabled|installed, disabled|installed|not installed)\s*(.*)$', line)
        if m:
            tokens = m.group(2).split()
            root = re.sub(r'/(\.agents/plugins|\.claude-plugin)/marketplace\.json$', '', path or '')
            return root, m.group(1), tokens[0] if tokens and re.match(r'\d', tokens[0]) else ''
    return None


def check_install(args) -> int:
    folder = Path(args.file)
    root = os.path.normpath(args.root) if args.root else str(REPO)
    problems = []
    listing = folder / 'plugin-list.txt'
    found = parse_plugin_list(listing.read_text(encoding='utf-8')) if listing.is_file() else None
    version = ''
    if not found:
        problems.append('plugin-list.txt has no my-agent@my-plugins row')
    else:
        market, status, version = found
        if status != 'installed, enabled':
            problems.append(f'my-agent@my-plugins is "{status}", not "installed, enabled"')
        if os.path.normpath(market) != root:
            problems.append(f'marketplace root is {market}, not {root}')
    source = folder / 'skills-source.txt'
    if not source.is_file() or source.read_text(encoding='utf-8').strip() not in ('prompt-input', 'session-record'):
        problems.append('skills evidence is not from a hard source')
    skills = folder / 'skills-list.txt'
    listed = [l.strip() for l in skills.read_text(encoding='utf-8').splitlines() if l.strip()] if skills.is_file() else []
    if listed.count('my-agent:monitor') != 1:
        problems.append(f'skills-list.txt holds my-agent:monitor {listed.count("my-agent:monitor")} time(s), not exactly once')
    if listed.count('my-agent:my-agent') != 1:
        problems.append(f'skills-list.txt holds my-agent:my-agent {listed.count("my-agent:my-agent")} time(s), not exactly once')
    cached = folder / 'cache' / version / 'codex-plugin.json' if version else None
    wanted = Path(root) / 'plugins' / 'my-agent' / '.codex-plugin' / 'plugin.json'
    if cached is None or not cached.is_file():
        problems.append(f'no cache copy of .codex-plugin/plugin.json for version {version or "?"} (an old Claude-format install has none)')
    elif not wanted.is_file():
        problems.append(f'missing {wanted}')
    elif load_json(cached) != load_json(wanted):
        problems.append('the cached .codex-plugin/plugin.json differs from the repository one')
    if args.version:
        if version != args.version:
            problems.append(f'plugin-list.txt shows version {version or "none"}, not {args.version}')
        if cached is not None and cached.is_file() and load_json(cached).get('version') != args.version:
            problems.append(f'the cached manifest version is {load_json(cached).get("version")}, not {args.version}')
    for problem in problems:
        print(problem)
    if not problems:
        print('listed: my-agent:my-agent, my-agent:monitor')
    return 1 if problems else 0


# ---- skills listing ----

SKILLS_INPUT_PROMPT = 'Reply with exactly: ok.'


# -- listing evidence rule --

ALIAS_LINE = re.compile(r'^[ \t]*[-*][ \t]+`(r\d+)`[ \t]*=[ \t]*`([^`\n]+)`[ \t]*$', re.M)
ENTRY_LINE = re.compile(r'^- (\S+):\s+((?:(?!\n- \S+:\s|\n[ \t]*\n).)*?)\s*\(file:\s*([^)\s]+)\)', re.M | re.S)
HOME_PATH = re.compile(r'/(?:Users|home)/[^/\s]+')


def resolve_alias(raw_path: str, aliases: dict) -> str:
    m = re.match(r'(r\d+)/(.*)$', raw_path, re.S)
    if not m:
        return raw_path
    root = aliases.get(m.group(1))
    return root.rstrip('/') + '/' + m.group(2) if root else 'unresolved'


def parse_listing(text: str):
    """(entries, aliases) of one decoded text: entries of the form `- name: description (file: path)`."""
    aliases = dict(ALIAS_LINE.findall(text))
    entries = []
    for m in ENTRY_LINE.finditer(text):
        entries.append({'name': m.group(1), 'description': m.group(2), 'raw_path': m.group(3),
                        'path': resolve_alias(m.group(3), aliases), 'line': text.count('\n', 0, m.start()) + 1})
    return entries, aliases


def norm_desc(text: str) -> str:
    text = re.sub(r'\s+', ' ', text).strip()
    return re.sub(r'(?:…|\.\.\.)$', '', text).strip()


def description_matches(entry_desc: str, skill_desc: str) -> bool:
    a, b = norm_desc(entry_desc), norm_desc(skill_desc)
    return bool(a) and (a == b or (len(a) >= 60 and b.startswith(a)))


def json_strings(value, depth=0):
    """Every string of a decoded JSON value; a string that is itself JSON is decoded too."""
    for node in walk(value):
        if isinstance(node, str):
            yield node
            if depth < 3 and node.lstrip()[:1] in ('{', '['):
                try:
                    inner = json.loads(node)
                except ValueError:
                    continue
                yield from json_strings(inner, depth + 1)


def text_strings(raw: str) -> list:
    """Strings of a text that may be JSON (as a whole, or one value per line); plain text stays as it is."""
    for parse in (lambda: [json.loads(raw)], lambda: [json.loads(l) for l in raw.splitlines() if l.strip()]):
        try:
            strings = [s for v in parse() for s in json_strings(v)]
        except ValueError:
            continue
        if strings:
            return strings
    return [raw]


def record_item_is_input(obj) -> bool:
    """A session record item that is neither model output nor a tool call nor a tool output, nor the probe's prompt."""
    if not isinstance(obj, dict):
        return False
    kind = obj.get('type')
    payload = obj.get('payload') if isinstance(obj.get('payload'), dict) else {}
    if kind in ('world_state', 'turn_context', 'session_meta'):
        return True
    if kind == 'response_item' and payload.get('type') == 'message' and payload.get('role') in ('developer', 'system', 'user'):
        return not (payload.get('role') == 'user' and any(SKILLS_INPUT_PROMPT in s for s in json_strings(payload)))
    return False


def listing_texts(path) -> list:
    """(line, decoded text) pairs of one source: a session record (.jsonl) or the output of `codex debug prompt-input`."""
    path = Path(path)
    raw = path.read_text(encoding='utf-8', errors='replace')
    if path.suffix == '.jsonl':
        out = []
        for n, line in enumerate(raw.splitlines(), 1):
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if record_item_is_input(obj):
                out += [(n, s) for s in json_strings(obj)]
        return out
    return [(0, s) for s in text_strings(raw)]


def all_entries(path) -> list:
    out = []
    for at, text in listing_texts(path):
        for e in parse_listing(text)[0]:
            out.append(dict(e, at=at or e['line']))
    return out


def distinct_entries(entries: list) -> list:
    seen, out = set(), []
    for e in entries:
        if (e['name'], e['path']) not in seen:
            seen.add((e['name'], e['path']))
            out.append(e)
    return out


def scrub_text(text: str, codex: Path) -> str:
    text = str(text)
    codex = str(codex).rstrip('/')
    if codex:
        text = text.replace(codex, '<codex-home>')
    text = re.sub(r'/(?:Users|home)/[^/\s]+/\.codex(?=/|\s|$)', '<codex-home>', text)
    text = text.replace(str(Path.home()), '<home>')
    return HOME_PATH.sub('<home>', text)


def frontmatter_description(path: Path):
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        return None
    parts = text.split('---')
    if not text.startswith('---') or len(parts) < 3:
        return None
    lines = parts[1].splitlines()
    for i, line in enumerate(lines):
        m = re.match(r'description:\s*(.*)$', line)
        if not m:
            continue
        value = m.group(1).strip()
        if value in ('>', '|', '>-', '|-'):
            block = []
            for nxt in lines[i + 1:]:
                if nxt[:1] not in (' ', '\t'):
                    break
                block.append(nxt.strip())
            return ' '.join(block)
        if len(value) > 1 and value[0] == value[-1] and value[0] in '\'"':
            value = value[1:-1].replace("''", "'") if value[0] == "'" else value[1:-1]
        return value
    return None


def my_agent_descriptions(codex: Path, market: str = 'my-plugins', plugin: str = 'my-agent') -> dict:
    """Frontmatter descriptions of my-agent's root skill and monitor in the installed copies (every version)."""
    base = codex / 'plugins' / 'cache' / market / plugin
    out = {'root': [], 'monitor': []}
    for version in sorted(p for p in base.glob('*') if p.is_dir()) if base.is_dir() else []:
        for key, rels in (('root', ('skills/my-agent/SKILL.md', 'SKILL.md')), ('monitor', ('skills/monitor/SKILL.md',))):
            desc = next((d for d in (frontmatter_description(version / rel) for rel in rels) if d), None)
            if desc:
                out[key].append(desc)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='probe.py', description=__doc__.split('\n')[0])
    parser.add_argument('--codex', default='codex', help='path of the codex binary')
    parser.add_argument('--codex-home', default=None, help='Codex home folder (default $CODEX_HOME or ~/.codex)')
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('snapshot')
    p.add_argument('--out', required=True)
    p.add_argument('--skills', default=None)
    p.add_argument('--cache', default=None)
    p = sub.add_parser('check')
    p.add_argument('what', choices=['install'])
    p.add_argument('file')
    p.add_argument('--root', default=None)
    p.add_argument('--version', default=None)
    args = parser.parse_args(argv)
    return {'snapshot': cmd_snapshot, 'check': cmd_check}[args.cmd](args)


if __name__ == '__main__':
    sys.exit(main())
