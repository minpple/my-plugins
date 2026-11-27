"""intake.py: the Intake script. `facts` (read-only: every fact Intake needs) and `create` (every Intake record)."""
import json
import os
import shlex
import sys
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from helpers import CLAUDE_HOOK_ENV, L4, clean_task_env, events, log_lines, parse, run_hook, run_script

sys.path.insert(0, str(L4 / 'scripts'))

SCRIPT = L4 / 'scripts' / 'intake.py'
TASK_DIR = '.my-agent'
TWO_PRESETS = {'dev': {'standard': {}, 'economy': {'coder': {'effort': 'low'}}}}
KEEP = ('MA_TASK_DIR', 'CLAUDE_PLUGIN_OPTION_TASK_DIR', 'MA_PROJECTS_FILE')   # always dropped from the child env


def git(repo, *args, check=True):
    return subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                          check=check, capture_output=True, text=True)


def init_repo(path, branch='main', commit=True):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    git(path, 'init', '-q')
    git(path, 'symbolic-ref', 'HEAD', f'refs/heads/{branch}')
    if commit:
        (path / 'f.txt').write_text('x')
        git(path, 'add', 'f.txt')
        git(path, 'commit', '-qm', 'first')
    return path


def snapshot(root):
    """{relative path: bytes, or None for a folder} of everything under `root`."""
    out = {}
    for dirpath, dirs, files in os.walk(root):
        for name in dirs:
            out[str((Path(dirpath) / name).relative_to(root))] = None
        for name in files:
            p = Path(dirpath) / name
            out[str(p.relative_to(root))] = p.read_bytes()
    return out


def parse_facts(stdout):
    """(header dict, with a list per 'presets <p>' key; [candidate dict with 'path', 'kind', 'paths' and its lines])."""
    head, cands, cur = {}, [], None
    for line in stdout.splitlines():
        if line.startswith('candidate: '):
            path, _, kind = line[len('candidate: '):].rpartition(' (')
            cur = {'path': path, 'kind': kind.rstrip(')'), 'paths': []}
            cands.append(cur)
        elif line.startswith('  ') and cur is not None:
            key, _, value = line.strip().partition(': ')
            if key == 'path':
                cur['paths'].append(value)
            else:
                cur[key] = value
        else:
            key, _, value = line.partition(': ')
            if key.startswith('presets '):
                head.setdefault(key, []).append(value)
            else:
                head[key] = value
    return head, cands


def parse_targets(stdout):
    """[{'target', 'resolved', 'location', 'exists', 'skip'}] of the `target:` lines, in order (parse_facts keeps one)."""
    return [dict(part.partition(': ')[::2] for part in line.split(' | '))
            for line in stdout.splitlines() if line.startswith('target: ')]


def expected_plugin(folder):
    """The `plugin:` value the design gives for `folder`: short hash of its last commit, `-dirty`, or none."""
    log = subprocess.run(['git', '-C', str(folder), 'log', '-1', '--format=%h', '--', '.'], capture_output=True, text=True)
    value = log.stdout.strip() if log.returncode == 0 else ''
    if not value:
        return 'none'
    status = subprocess.run(['git', '-C', str(folder), 'status', '--porcelain', '--', '.'], capture_output=True, text=True)
    return value + ('-dirty' if status.stdout.strip() else '')


class FactsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.data = self.root / 'data'
        self.data.mkdir()
        (self.root / 'statusline-empty').mkdir()
        self.env = {'MA_DATA_DIR': str(self.data), 'CLAUDE_CODE_SESSION_ID': 's-1',
                    'MA_STATUSLINE_DIR': str(self.root / 'statusline-empty'),
                    'MA_CLAUDE_PROJECTS': str(self.root / 'projects'), 'MA_HOST': ''}
        self.drop = KEEP + ('CLAUDE_PLUGIN_ROOT', 'CODEX_THREAD_ID')

    def tearDown(self):
        self.tmp.cleanup()

    def facts(self, cwd, *args, env=None, drop=None):
        return run_script(SCRIPT, 'facts', *args, '--cwd', str(cwd), env=dict(self.env, **(env or {})), cwd=self.root,
                          drop=self.drop if drop is None else drop)

    def parsed(self, cwd, *args, **kw):
        r = self.facts(cwd, *args, **kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        return parse_facts(r.stdout)

    def write_models(self, obj):
        text = obj if isinstance(obj, str) else json.dumps(obj)
        (self.data / 'agent-models.json').write_text(text, encoding='utf-8')


class FactsTest(FactsBase):
    def test_clean_repo_on_a_branch(self):
        repo = init_repo(self.root / 'repo', branch='work')
        r = self.facts(repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        keys = [line.split(':')[0] for line in r.stdout.splitlines() if not line.startswith(' ')]
        self.assertEqual(keys[:8], ['data', 'task_dir', 'run', 'run_git', 'index', 'session', 'plugin', 'date'])
        head, cands = parse_facts(r.stdout)
        self.assertEqual((head['data'], head['task_dir'], head['run'], head['run_git']),
                         (str(self.data), TASK_DIR, str(repo), str(repo)))
        self.assertEqual((head['index'], head['session']), ('none', 's-1'))
        self.assertEqual(head['date'], datetime.now().strftime('%y%m%d'))
        self.assertEqual(len(cands), 1)
        c = cands[0]
        self.assertEqual((c['path'], c['kind'], c['active'], c['git'], c['branch'], c['uncommitted']),
                         (str(repo), 'repo', 'none', 'true', 'work', '0'))
        self.assertEqual((c['gitignore'], c['ids'], c['listed']), ('ask', 'none', 'no'))

    def test_session_none_without_env(self):
        repo = init_repo(self.root / 'repo')
        head, _ = self.parsed(repo, drop=self.drop + ('CLAUDE_CODE_SESSION_ID',))
        self.assertEqual(head['session'], 'none')

    def test_uncommitted_drops_derived_and_task_dir_paths(self):
        repo = init_repo(self.root / 'repo')
        (repo / '__pycache__').mkdir()
        (repo / '__pycache__' / 'x.pyc').write_text('c')
        (repo / 'pkg').mkdir()
        (repo / 'pkg' / 'y.pyc').write_text('c')
        (repo / TASK_DIR / 't1').mkdir(parents=True)
        (repo / TASK_DIR / 't1' / 'plan.md').write_text('p')
        (repo / 'f.txt').write_text('changed')
        (repo / 'new.md').write_text('n')
        _, cands = self.parsed(repo)
        c = cands[0]
        self.assertEqual(c['uncommitted'], '2')
        self.assertEqual(sorted(c['paths']), [' M f.txt', '?? new.md'])

    def test_uncommitted_lists_ten_then_more(self):
        repo = init_repo(self.root / 'repo')
        for i in range(13):
            (repo / f'n{i:02}.md').write_text('n')
        _, cands = self.parsed(repo)
        c = cands[0]
        self.assertEqual(c['uncommitted'], '13')
        self.assertEqual(len(c['paths']), 11)
        self.assertEqual(c['paths'][-1], '… 3 more')

    def test_detached_head(self):
        repo = init_repo(self.root / 'repo')
        git(repo, 'checkout', '-q', '--detach')
        _, cands = self.parsed(repo)
        self.assertEqual(cands[0]['branch'], '(detached)')

    def test_gitignore_ignored_file_ask(self):
        repo = init_repo(self.root / 'repo')
        _, cands = self.parsed(repo)
        self.assertEqual(cands[0]['gitignore'], 'ask')
        (repo / TASK_DIR).mkdir()
        (repo / TASK_DIR / '.gitignore').write_text('# my-agent: commit\n')
        _, cands = self.parsed(repo)
        self.assertEqual(cands[0]['gitignore'], 'file')
        (repo / TASK_DIR / '.gitignore').write_text('*\n')
        _, cands = self.parsed(repo)
        self.assertEqual(cands[0]['gitignore'], 'ignored')
        (repo / TASK_DIR / '.gitignore').unlink()
        (repo / '.gitignore').write_text(f'{TASK_DIR}/\n')
        _, cands = self.parsed(repo)
        self.assertEqual(cands[0]['gitignore'], 'ignored')

    def test_active_task_and_broken(self):
        repo = init_repo(self.root / 'repo')
        (repo / TASK_DIR).mkdir()
        (repo / TASK_DIR / '.active').write_text('task: 261115-x\nphase: 3\nsession: s-0\nstarted: 2026-11-15 14:02\n')
        _, cands = self.parsed(repo)
        self.assertEqual(cands[0]['active'], '261115-x phase 3 session s-0 started 2026-11-15 14:02')
        (repo / TASK_DIR / '.active').write_text('phase: 3\n')
        _, cands = self.parsed(repo)
        self.assertEqual(cands[0]['active'], f'broken ({repo / TASK_DIR / ".active"})')

    def test_ids_of_today_only(self):
        repo = init_repo(self.root / 'repo')
        today = datetime.now().strftime('%y%m%d')
        for name in (f'{today}-b-task', f'{today}-a-task', '200101-old'):
            (repo / TASK_DIR / name).mkdir(parents=True)
        (repo / TASK_DIR / f'{today}-file').write_text('not a folder')
        _, cands = self.parsed(repo)
        self.assertEqual(cands[0]['ids'], f'{today}-a-task, {today}-b-task')

    def test_custom_task_dir(self):
        repo = init_repo(self.root / 'repo')
        (repo / 'docs' / 'agent' / 't').mkdir(parents=True)
        (repo / 'docs' / 'agent' / '.active').write_text('task: t\nphase: 1\nsession: \nstarted: now\n')
        head, cands = self.parsed(repo, '--task-dir', 'docs/agent')
        self.assertEqual(head['task_dir'], 'docs/agent')
        self.assertTrue(cands[0]['active'].startswith('t phase 1'))

    def test_outside_git_candidates(self):
        run = self.root / 'notes'
        run.mkdir()
        drafts = self.root / 'drafts'
        (drafts / TASK_DIR).mkdir(parents=True)
        (drafts / TASK_DIR / '.active').write_text('task: 261115-d\nphase: 2\nsession: s-9\nstarted: t\n')
        given = self.root / 'given'
        given.mkdir()
        (self.data / 'active-index.json').write_text(json.dumps({str(run): str(drafts), '/elsewhere': '/x'}))
        (self.data / 'projects.txt').write_text(f'# comment\n{drafts}\n')
        head, cands = self.parsed(run, '--candidate', str(given))
        self.assertEqual((head['run_git'], head['index']), ('none', str(drafts)))
        self.assertEqual([(c['path'], c['kind']) for c in cands],
                         [(str(drafts), 'index'), (str(self.data), 'data'), (str(run), 'current'),
                          (str(given), 'given')])
        self.assertEqual([c['git'] for c in cands], ['false'] * 4)
        self.assertEqual([c['listed'] for c in cands], ['yes', 'no', 'no', 'no'])
        self.assertEqual(cands[0]['active'], '261115-d phase 2 session s-9 started t')
        for c in cands:
            self.assertNotIn('branch', c)
            self.assertNotIn('uncommitted', c)

    def test_index_entry_of_an_ancestor_of_the_run_folder(self):
        run = self.root / 'notes' / 'sub'
        run.mkdir(parents=True)
        (self.data / 'active-index.json').write_text(json.dumps({str(self.root / 'notes'): str(self.root / 'loc')}))
        head, _ = self.parsed(run)
        self.assertEqual(head['index'], str(self.root / 'loc'))

    def test_given_candidate_inside_git_run(self):
        repo = init_repo(self.root / 'repo')
        other = init_repo(self.root / 'other')
        _, cands = self.parsed(repo, '--candidate', str(other))
        self.assertEqual([(c['path'], c['kind']) for c in cands], [(str(repo), 'repo'), (str(other), 'given')])
        self.assertEqual(cands[1]['git'], 'true')
        self.assertEqual(cands[1]['gitignore'], 'ask')

    def test_listed_yes_and_no(self):
        repo = init_repo(self.root / 'repo')
        _, cands = self.parsed(repo)
        self.assertEqual(cands[0]['listed'], 'no')
        (self.data / 'projects.txt').write_text(f'{repo}/../repo\n')
        _, cands = self.parsed(repo)
        self.assertEqual(cands[0]['listed'], 'yes')

    def test_presets_two_none_and_error(self):
        repo = init_repo(self.root / 'repo')
        head, _ = self.parsed(repo)
        self.assertEqual(head['presets dev'], ['none'])
        self.write_models(TWO_PRESETS)
        head, _ = self.parsed(repo)
        self.assertEqual(head['presets dev'], ['standard', 'economy: coder sonnet/low'])
        self.assertEqual(head['presets general'], ['none'])
        self.write_models({'dev': {'fast': {'planner': {'model': 'haiku'}}}})
        head, _ = self.parsed(repo)
        for p in ('general', 'research', 'dev'):
            self.assertEqual(len(head[f'presets {p}']), 1)
            self.assertTrue(head[f'presets {p}'][0].startswith('error: agent-models: '), head[f'presets {p}'])

    def test_presets_lines_for_two_made_up_presets(self):
        repo = init_repo(self.root / 'repo')
        self.write_models({'dev': {'thorough': {'coder': {'model': 'opus', 'effort': 'high'}},
                                   'lean': {'coder': {'model': 'haiku', 'effort': 'low'}}}})
        head, _ = self.parsed(repo)
        lines = {line.partition(':')[0]: line for line in head['presets dev']}
        self.assertEqual(set(lines), {'thorough', 'lean'})
        self.assertEqual(lines['thorough'], 'thorough: coder opus/high')
        self.assertEqual(lines['lean'], 'lean: coder haiku/low')
        self.assertEqual(head['presets research'], ['none'])

    def test_header_order_before_candidates(self):
        repo = init_repo(self.root / 'repo')
        lines = self.facts(repo).stdout.splitlines()
        self.assertEqual([x.split(':')[0] for x in lines[7:12]],
                         ['date', 'presets general', 'presets research', 'presets dev', 'candidate'])

    def test_plugin_from_subfolder_of_a_repo(self):
        repo = init_repo(self.root / 'plugrepo', commit=False)
        for name in ('mine', 'other'):
            (repo / name).mkdir()
            (repo / name / 'f').write_text(name)
            git(repo, 'add', name)
            git(repo, 'commit', '-qm', name)
        mine = git(repo, 'log', '-1', '--format=%h', '--', 'mine').stdout.strip()
        run = init_repo(self.root / 'run')
        env = {'CLAUDE_PLUGIN_ROOT': str(repo / 'mine')}
        head, _ = self.parsed(run, env=env, drop=KEEP)
        self.assertEqual(head['plugin'], mine)
        (repo / 'other' / 'f').write_text('changed')
        git(repo, 'commit', '-qam', 'other again')
        head, _ = self.parsed(run, env=env, drop=KEEP)
        self.assertEqual(head['plugin'], mine)
        (repo / 'mine' / 'f').write_text('dirty')
        head, _ = self.parsed(run, env=env, drop=KEEP)
        self.assertEqual(head['plugin'], mine + '-dirty')

    def test_plugin_none_outside_git_or_without_commit(self):
        run = init_repo(self.root / 'run')
        plain = self.root / 'plain'
        plain.mkdir()
        head, _ = self.parsed(run, env={'CLAUDE_PLUGIN_ROOT': str(plain)}, drop=KEEP)
        self.assertEqual(head['plugin'], 'none')
        empty = init_repo(self.root / 'empty', commit=False)
        head, _ = self.parsed(run, env={'CLAUDE_PLUGIN_ROOT': str(empty)}, drop=KEEP)
        self.assertEqual(head['plugin'], 'none')

    def test_plugin_default_root(self):
        run = init_repo(self.root / 'run')
        head, _ = self.parsed(run)   # CLAUDE_PLUGIN_ROOT is dropped: the folder of this plugin
        self.assertEqual(head['plugin'], expected_plugin(Path(SCRIPT).resolve().parents[2]))

    def test_writes_nothing(self):
        repo = init_repo(self.root / 'repo')
        (repo / 'new.md').write_text('n')
        (self.data / 'projects.txt').write_text('x\n')
        before = snapshot(self.root)
        self.assertEqual(self.facts(repo, '--candidate', str(self.root / 'nowhere')).returncode, 0)
        self.assertEqual(self.facts(self.root / 'nowhere').returncode, 0)
        self.assertEqual(snapshot(self.root), before)

    def test_missing_candidate_folder_is_not_git(self):
        repo = init_repo(self.root / 'repo')
        _, cands = self.parsed(repo, '--candidate', str(self.root / 'nowhere'))
        self.assertEqual((cands[1]['git'], cands[1]['active'], cands[1]['ids']), ('false', 'none', 'none'))

    def test_codex_hook_health_stops(self):
        repo = init_repo(self.root / 'repo')
        tmpdir = self.root / 'tmp'
        tmpdir.mkdir()
        env = {'MA_HOST': 'codex', 'CODEX_THREAD_ID': '019a0000-0000-7000-8000-000000000001', 'TMPDIR': str(tmpdir)}
        r = self.facts(repo, env=env, drop=KEEP + ('CLAUDE_CODE_SESSION_ID', 'CLAUDECODE', 'CLAUDE_PLUGIN_ROOT'))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, '')
        self.assertIn('trust', r.stderr)

    def test_bad_arguments_exit_2(self):
        for args in (['facts', '--bogus'], ['bogus'], []):
            r = run_script(SCRIPT, *args, env=self.env, cwd=self.root, drop=self.drop)
            self.assertEqual(r.returncode, 2, args)



class TargetTest(FactsBase):
    """The `target:` lines of `facts --candidate`: lookup, task location mapping and skip (new-task.md item 2)."""

    def targets(self, cwd, *candidates, env=None, drop=None):
        args = [a for c in candidates for a in ('--candidate', str(c))]
        r = self.facts(cwd, *args, env=env, drop=drop)
        self.assertEqual(r.returncode, 0, r.stderr)
        return parse_targets(r.stdout), parse_facts(r.stdout)[1], r.stdout

    def blocks(self, cands):
        return [(c['path'], c['kind']) for c in cands]

    def test_given_file_maps_to_its_folder(self):
        run = init_repo(self.root / 'repo')
        notes = self.root / 'notes'
        notes.mkdir()
        (notes / 'a.md').write_text('a')
        targets, cands, _ = self.targets(run, notes / 'a.md')
        self.assertEqual(targets, [{'target': str(notes / 'a.md'), 'resolved': str(notes / 'a.md'),
                                    'location': str(notes), 'exists': 'yes', 'skip': 'no'}])
        self.assertEqual(self.blocks(cands), [(str(run), 'repo'), (str(notes), 'given')])

    def test_given_subfolder_maps_to_repo_root(self):
        repo = init_repo(self.root / 'repo')
        (repo / 'sub').mkdir()
        (repo / 'sub' / 'g.txt').write_text('g')
        targets, cands, _ = self.targets(repo, repo / 'sub', repo / 'sub' / 'g.txt')
        self.assertEqual([(t['location'], t['exists'], t['skip']) for t in targets],
                         [(str(repo), 'yes', 'no'), (str(repo), 'yes', 'no')])
        self.assertEqual(self.blocks(cands), [(str(repo), 'repo')])

    def test_given_link_is_followed(self):
        run = init_repo(self.root / 'run')
        src = init_repo(self.root / 'skills-src')
        (src / 'my-skill').mkdir()
        plain = self.root / 'plain-skills' / 'other-skill'
        plain.mkdir(parents=True)
        links = self.root / 'config' / 'skills'
        links.mkdir(parents=True)
        (links / 'my-skill').symlink_to(src / 'my-skill')
        (links / 'other-skill').symlink_to(plain)
        targets, cands, _ = self.targets(run, links / 'my-skill', links / 'other-skill')
        self.assertEqual([(t['resolved'], t['location']) for t in targets],
                         [(str(src / 'my-skill'), str(src)), (str(plain), str(plain))])
        self.assertEqual(self.blocks(cands), [(str(run), 'repo'), (str(src), 'given'), (str(plain), 'given')])

    def linked_worktree(self):
        main = init_repo(self.root / 'main')
        wt = self.root / 'wt'
        git(main, 'worktree', 'add', '-q', '-b', 'task-x', str(wt))
        (wt / 'sub').mkdir()
        return main, wt

    def test_given_in_linked_worktree_maps_to_worktree_top(self):
        _, wt = self.linked_worktree()
        run = init_repo(self.root / 'run')
        targets, cands, _ = self.targets(run, wt / 'sub')
        self.assertEqual(targets[0]['location'], str(wt))
        self.assertEqual(self.blocks(cands), [(str(run), 'repo'), (str(wt), 'given')])

    def test_run_folder_in_linked_worktree(self):
        _, wt = self.linked_worktree()
        head, cands = self.parsed(wt / 'sub')
        self.assertEqual(head['run_git'], str(wt))
        self.assertEqual(self.blocks(cands), [(str(wt), 'repo')])

    def test_target_lines_in_order_with_deduplicated(self):
        repo = init_repo(self.root / 'repo')
        (repo / 'sub').mkdir()
        other = init_repo(self.root / 'other')
        (other / 'docs').mkdir()
        targets, cands, stdout = self.targets(repo, repo / 'sub', other / 'docs')
        self.assertEqual([(t['target'], t['location']) for t in targets],
                         [(str(repo / 'sub'), str(repo)), (str(other / 'docs'), str(other))])
        keys = [line.split(':')[0] for line in stdout.splitlines() if not line.startswith(' ')]
        self.assertEqual(keys[8:14], ['presets general', 'presets research', 'presets dev', 'target', 'target',
                                      'candidate'])
        self.assertEqual(self.blocks(cands), [(str(repo), 'repo'), (str(other), 'given')])

    def test_relative_target_looked_up_from_run_folder_then_root(self):
        repo = init_repo(self.root / 'repo')
        run = repo / 'sub'
        (run / 'x').mkdir(parents=True)
        (repo / 'y').mkdir()
        for name in ('x', 'y', 'z'):   # the process folder of facts holds every name: it must not be used
            (self.root / name).mkdir()
        targets, _, _ = self.targets(run, 'x', 'y', 'z')
        self.assertEqual([(t['target'], t['resolved'], t['exists']) for t in targets],
                         [('x', str(run / 'x'), 'yes'), ('y', str(repo / 'y'), 'yes'), ('z', str(run / 'z'), 'no')])
        self.assertEqual([t['location'] for t in targets], [str(repo), str(repo), str(run / 'z')])

    def test_given_root_with_active_task(self):
        run = self.root / 'plain'
        run.mkdir()
        proj = init_repo(self.root / 'proj')
        (proj / 'sub').mkdir()
        (proj / TASK_DIR).mkdir()
        (proj / TASK_DIR / '.active').write_text('task: 261126-x\nphase: 2\nsession: s-0\nstarted: t\n')
        targets, cands, _ = self.targets(run, proj / 'sub')
        self.assertEqual(targets[0]['location'], str(proj))
        given = [c for c in cands if c['kind'] == 'given']
        self.assertEqual([c['path'] for c in given], [str(proj)])
        self.assertEqual((given[0]['active'], given[0]['git']), ('261126-x phase 2 session s-0 started t', 'true'))

    def test_given_folder_outside_git(self):
        run = init_repo(self.root / 'repo')
        plain = self.root / 'plain'
        plain.mkdir()
        targets, cands, _ = self.targets(run, plain)
        self.assertEqual((targets[0]['location'], targets[0]['exists']), (str(plain), 'yes'))
        self.assertEqual((cands[1]['path'], cands[1]['kind'], cands[1]['git']), (str(plain), 'given', 'false'))

    def test_missing_target_says_so(self):
        run = init_repo(self.root / 'repo')
        empty = self.root / 'empty'
        empty.mkdir()
        targets, cands, _ = self.targets(run, self.root / 'nowhere', empty)
        self.assertEqual([(t['resolved'], t['location'], t['exists'], t['skip']) for t in targets],
                         [(str(self.root / 'nowhere'), str(self.root / 'nowhere'), 'no', 'no'),
                          (str(empty), str(empty), 'yes', 'no')])
        self.assertEqual((cands[1]['path'], cands[1]['git'], cands[1]['active']), (str(self.root / 'nowhere'), 'false', 'none'))

    def test_target_of_an_unknown_user_home_is_missing(self):
        """`~<unknown user>` cannot be expanded: a missing target, and the call goes on."""
        run = init_repo(self.root / 'repo')
        raws = ['~ma-no-such-user-q7/x', '~ma-no-such-user-q7/y']
        (run / raws[0]).mkdir(parents=True)   # a leading `~` is never looked up as a relative path
        other = self.root / 'other'
        other.mkdir()
        targets, cands, _ = self.targets(run, *raws, other)
        self.assertEqual([(t['target'], t['location'], t['exists'], t['skip']) for t in targets],
                         [(raws[0], str(run / raws[0]), 'no', 'no'), (raws[1], str(run / raws[1]), 'no', 'no'),
                          (str(other), str(other), 'yes', 'no')])
        self.assertEqual(self.blocks(cands), [(str(run), 'repo'), (str(run / raws[0]), 'given'),
                                              (str(run / raws[1]), 'given'), (str(other), 'given')])

    def test_target_in_data_folder_is_skipped(self):
        proj = init_repo(self.root / 'proj')
        real = proj / 'data-real'
        (real / 'notes').mkdir(parents=True)
        (real / 'notes' / 'x.md').write_text('x')
        (proj / 'other.md').write_text('o')
        link = self.root / 'data-link'
        link.symlink_to(real)
        run = init_repo(self.root / 'run')
        targets, _, stdout = self.targets(run, real / 'notes' / 'x.md', link / 'notes' / 'x.md', proj / 'other.md',
                                          env={'MA_DATA_DIR': str(link)})
        self.assertIn(f'data: {link}', stdout.splitlines())
        self.assertEqual([(t['location'], t['skip']) for t in targets],
                         [(str(proj), 'data folder'), (str(proj), 'data folder'), (str(proj), 'no')])
        # data folder outside git, session run from it: the skip changes no block
        (self.data / 'n.md').write_text('n')
        _, plain_cands, _ = self.targets(self.data)
        targets, cands, _ = self.targets(self.data, self.data / 'n.md')
        self.assertEqual([(t['location'], t['skip']) for t in targets], [(str(self.data), 'data folder')])
        self.assertEqual(cands, plain_cands)
        self.assertEqual(self.blocks(cands), [(str(self.data), 'data')])
        for c in cands:
            self.assertNotIn('skip', c)

    def test_target_in_plugin_cache_is_skipped(self):
        real = self.root / 'real-plugins'
        skill = real / 'cache' / 'mkt' / 'some-plugin' / '1.0.0' / 'skills' / 'some-skill'
        skill.mkdir(parents=True)
        config = self.root / 'config'
        config.mkdir()
        (config / 'plugins').symlink_to(real)
        (self.root / 'skills').mkdir()
        (self.root / 'skills' / 'some-skill').symlink_to(skill)
        run = init_repo(self.root / 'run')
        inside = config / 'plugins' / 'cache' / 'mkt' / 'some-plugin' / '1.0.0' / 'skills' / 'some-skill'
        targets, _, _ = self.targets(run, inside, self.root / 'skills' / 'some-skill', run,
                                     env={'CLAUDE_CONFIG_DIR': str(config)})
        self.assertEqual([(t['resolved'], t['skip']) for t in targets],
                         [(str(skill), 'plugin cache'), (str(skill), 'plugin cache'), (str(run), 'no')])
        other_root = self.root / 'host' / 'plugins' / 'cache' / 'm' / 'p' / '2.0'
        (other_root / 'skills' / 't').mkdir(parents=True)
        targets, _, _ = self.targets(run, other_root / 'skills' / 't', run,
                                     env={'CLAUDE_CONFIG_DIR': str(config), 'CLAUDE_PLUGIN_ROOT': str(other_root)},
                                     drop=KEEP)
        self.assertEqual([t['skip'] for t in targets], ['plugin cache', 'no'])

    def test_target_in_codex_plugin_cache_is_skipped(self):
        """Codex's install cache (`<codex home>/plugins/cache`, tools/codex-probe/probe.py) is skipped on every host."""
        run = init_repo(self.root / 'run')
        for home, env in ((self.root / 'codex-home', {'CODEX_HOME': str(self.root / 'codex-home')}),
                          (self.root / 'user' / '.codex', {'CODEX_HOME': '', 'HOME': str(self.root / 'user')})):
            skill = home / 'plugins' / 'cache' / 'mkt' / 'p' / '1.0.0' / 'skills' / 's'
            skill.mkdir(parents=True)
            own = home / 'skills' / 'mine'
            own.mkdir(parents=True)
            targets, _, _ = self.targets(run, skill, own, env=env)
            self.assertEqual([t['skip'] for t in targets], ['plugin cache', 'no'], env)


NAME = 'claude-opus-5-5'
KINDS = ['step', 'ask', 'answer', 'delegate', 'models', 'profile']


class BehindTest(FactsBase):
    """The `behind:` line of `facts`: every remote is a local bare repository, so nothing uses the network."""

    def setUp(self):
        super().setUp()
        self.bare = self.root / 'origin.git'
        self.bare.mkdir()
        git(self.bare, 'init', '-q', '--bare')
        git(self.bare, 'symbolic-ref', 'HEAD', 'refs/heads/main')
        self.seed = init_repo(self.root / 'seed')
        git(self.seed, 'remote', 'add', 'origin', str(self.bare))
        git(self.seed, 'push', '-q', 'origin', 'main')
        self.pushed = 0

    def clone(self):
        subprocess.run(['git', 'clone', '-q', str(self.bare), str(self.root / 'repo')], check=True, capture_output=True)
        return self.root / 'repo'

    def push_commits(self, n):
        for _ in range(n):
            self.pushed += 1
            (self.seed / f'g{self.pushed}.txt').write_text('x')
            git(self.seed, 'add', '.')
            git(self.seed, 'commit', '-qm', f'more {self.pushed}')
        git(self.seed, 'push', '-q', 'origin', 'main')

    def behind(self, repo):
        _, cands = self.parsed(repo)
        return cands[0]['behind']

    def test_behind_counts_commits_on_origin_default(self):
        repo = self.clone()
        self.assertEqual(self.behind(repo), '0 (origin/main)')
        self.push_commits(3)
        self.assertEqual(self.behind(repo), '3 (origin/main)')
        git(repo, 'remote', 'set-head', 'origin', '-d')   # no origin/HEAD: the default branch comes from ls-remote
        self.assertEqual(git(repo, 'symbolic-ref', '-q', 'refs/remotes/origin/HEAD', check=False).returncode, 1)
        self.push_commits(1)
        self.assertEqual(self.behind(repo), '4 (origin/main)')

    def test_behind_counts_a_branch_never_pushed(self):
        repo = self.clone()
        git(repo, 'checkout', '-q', '-b', 'feature')
        (repo / 'mine.txt').write_text('m')
        git(repo, 'add', 'mine.txt')
        git(repo, 'commit', '-qm', 'mine')
        self.push_commits(2)
        self.assertEqual(self.behind(repo), '2 (origin/main)')

    def test_behind_line_comes_after_path_lines_before_gitignore(self):
        repo = self.clone()
        (repo / 'new.txt').write_text('n')
        r = self.facts(repo)
        lines = [line.split(':')[0].strip() for line in r.stdout.splitlines() if line.startswith('  ')]
        self.assertEqual(lines, ['active', 'git', 'branch', 'uncommitted', 'path', 'behind', 'gitignore', 'ids', 'listed'])

    def test_behind_no_remote(self):
        self.assertEqual(self.behind(init_repo(self.root / 'plain')), 'not counted (no remote)')

    def test_behind_no_origin_remote(self):
        repo = init_repo(self.root / 'plain')
        git(repo, 'remote', 'add', 'upstream', str(self.bare))
        self.assertEqual(self.behind(repo), 'not counted (no origin remote)')

    def test_behind_detached_head(self):
        repo = self.clone()
        git(repo, 'checkout', '-q', '--detach')
        self.assertEqual(self.behind(repo), 'not counted (detached HEAD)')

    def test_behind_origin_without_default_branch(self):
        empty = self.root / 'empty.git'
        empty.mkdir()
        git(empty, 'init', '-q', '--bare')
        repo = init_repo(self.root / 'plain')
        git(repo, 'remote', 'add', 'origin', str(empty))
        self.assertEqual(self.behind(repo), 'not counted (origin has no default branch)')

    def test_behind_fetch_failed(self):
        repo = init_repo(self.root / 'plain')
        git(repo, 'remote', 'add', 'origin', str(self.root / 'gone'))
        value = self.behind(repo)
        self.assertTrue(value.startswith('not counted (fetch failed: '), value)
        self.assertIn('gone', value)
        self.assertEqual(len(value.splitlines()), 1)
        repo = self.clone()   # the default branch is known, the fetch itself fails
        self.bare.rename(self.root / 'moved.git')
        value = self.behind(repo)
        self.assertTrue(value.startswith('not counted (fetch failed: '), value)

    def test_behind_fetch_timeout(self):
        import intake
        repo = self.clone()
        real, seen = subprocess.run, []

        def runner(cmd, *args, **kw):
            if 'fetch' in cmd:
                seen.append((kw.get('timeout'), (kw.get('env') or {}).get('GIT_TERMINAL_PROMPT')))
                raise subprocess.TimeoutExpired(cmd, kw.get('timeout'))
            return real(cmd, *args, **kw)

        with mock.patch.object(intake.subprocess, 'run', runner):
            value = intake.behind(repo)
        self.assertEqual(value, 'not counted (fetch timed out after 10 s)')
        self.assertEqual(intake.FETCH_TIMEOUT, 10)
        self.assertEqual(seen, [(10, '0')])

    def test_behind_ls_remote_timeout(self):
        import intake
        repo = self.clone()
        git(repo, 'remote', 'set-head', 'origin', '-d')
        real = subprocess.run

        def runner(cmd, *args, **kw):
            if 'ls-remote' in cmd:
                raise subprocess.TimeoutExpired(cmd, kw.get('timeout'))
            return real(cmd, *args, **kw)

        with mock.patch.object(intake.subprocess, 'run', runner):
            self.assertEqual(intake.behind(repo), 'not counted (fetch timed out after 10 s)')


class CreateBase(FactsBase):
    def setUp(self):
        super().setUp()
        (self.data / 'monitor-config.json').write_text('{"autostart": false}', encoding='utf-8')
        self.repo = init_repo(self.root / 'repo', branch='work')
        self.today = datetime.now().strftime('%y%m%d')

    def create(self, *args, cwd=None, loc=None, env=None, drop=None, slug='probe-task'):
        base = ['--loc', str(loc or self.repo), '--profile', 'general', '--request=do the thing', '--model', NAME]
        if slug:
            base += ['--slug', slug]
        return run_script(SCRIPT, 'create', *base, *args, '--cwd', str(cwd or self.repo), '--data-dir', str(self.data),
                          '--task-dir', TASK_DIR, env=dict(self.env, **(env or {})), cwd=self.root,
                          drop=self.drop if drop is None else drop)

    def ok(self, *args, **kw):
        r = self.create(*args, **kw)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def task_folder(self, loc=None, name=None):
        return Path(loc or self.repo) / TASK_DIR / (name or f'{self.today}-probe-task')

    def intake(self, folder):
        out = {}
        for line in (folder / 'intake.md').read_text(encoding='utf-8').splitlines():
            key, _, value = line.partition(': ')
            out[key] = value
        return out

    def kinds(self, folder):
        return [line.split(' ')[2].rstrip(':') for line in log_lines(folder)]

    def statusline(self, usd=1.5):
        (self.root / 'statusline-empty' / 's-1.json').write_text(json.dumps({'cost_usd': usd}))


class CreateTest(CreateBase):
    def test_every_option_inside_git(self):
        self.write_models(TWO_PRESETS)
        self.statusline()
        r = self.ok('--profile', 'dev', '--gitignore', 'ignore', '--preset', 'economy', '--follows', '261115-earlier',
                    '--auto', '--router-pick', 'research',
                    '--ask', 'gate=Q q="Pick one" rec=A qn=1', '--ask', 'gate=Q q="Then?" rec=B qn=2',
                    '--answer', 'gate=Q choice=A qn=1', '--answer', 'gate=Q choice=Other other=1 qn=2')
        folder = self.task_folder()
        self.assertEqual((self.repo / TASK_DIR / '.gitignore').read_text(), '*\n')
        active = (self.repo / TASK_DIR / '.active').read_text().splitlines()
        self.assertEqual(active[:3], [f'task: {self.today}-probe-task', 'phase: 1', 'session: s-1'])
        self.assertRegex(active[3], r'^started: \d{4}-\d\d-\d\d \d\d:\d\d$')
        self.assertEqual(len(active), 4)
        self.assertEqual(self.kinds(folder), ['step', 'cost', 'ask', 'ask', 'answer', 'answer', 'delegate', 'models',
                                              'profile'])
        lines = log_lines(folder)
        self.assertEqual(lines[0].split(' ', 3)[3].split(' rev=')[0], 'n=1A name=Intake')
        self.assertEqual(parse(lines[1])['baseline'], '1')
        self.assertEqual((parse(lines[2])['qn'], parse(lines[3])['qn']), ('1', '2'))
        self.assertEqual(parse(lines[5])['other'], '1')
        self.assertEqual((parse(lines[6])['state'], parse(lines[6])['how']), ('on', 'flag'))
        self.assertEqual((parse(lines[7])['preset'], parse(lines[7])['source']), ('economy', 'file'))
        p = parse(lines[8])
        self.assertEqual((p['from'], p['to'], p['back'], p['archive']), ('research', 'dev', '-', '-'))
        intake = self.intake(folder)
        self.assertEqual((intake['Follows'], intake['Models'], intake['Profile']), ('261115-earlier', 'economy', 'dev'))
        out = dict(line.partition(': ')[::2] for line in r.stdout.splitlines())
        self.assertEqual(out['task'], f'{self.today}-probe-task')
        self.assertEqual(out['folder'], str(folder))
        self.assertEqual(out['monitor'], 'not started (autostart off)')
        self.assertIn('.gitignore', out['written'])
        self.assertIn('run-log 9 lines', out['written'])
        self.assertEqual(list(self.data.glob('active-index.json')), [])
        self.assertEqual((self.data / 'projects.txt').read_text().split(), [str(self.repo)])

    def test_intake_md_lines_and_order(self):
        self.ok()
        folder = self.task_folder()
        lines = (folder / 'intake.md').read_text(encoding='utf-8').splitlines()
        self.assertEqual(lines[0], 'Status: active')
        self.assertEqual([x.split(':')[0] for x in lines], ['Status', 'my-agent', 'Location', 'Profile', 'Task', 'Request'])
        self.assertEqual(lines[2], f'Location: {self.repo}')
        self.assertEqual(lines[5], 'Request: do the thing')
        self.assertEqual(self.kinds(folder), ['step'])

    def test_commit_choice_line(self):
        self.ok('--gitignore', 'commit')
        self.assertEqual((self.repo / TASK_DIR / '.gitignore').read_text(), '# my-agent: commit\n')

    def test_outside_git_adds_index_entry_and_keeps_others(self):
        loc = self.root / 'drafts'
        loc.mkdir()
        run = self.root / 'notes'
        run.mkdir()
        (self.data / 'active-index.json').write_text(json.dumps({'/elsewhere': '/x'}))
        r = self.ok(loc=loc, cwd=run)
        index = json.loads((self.data / 'active-index.json').read_text())
        self.assertEqual(index, {'/elsewhere': '/x', str(run): str(loc)})
        self.assertIn('active-index.json line', r.stdout)
        self.assertIn('projects.txt line', r.stdout)
        self.assertEqual(self.kinds(self.task_folder(loc)), ['step'])

    def test_no_index_line_when_location_is_the_run_folder(self):
        loc = self.root / 'here'
        loc.mkdir()
        self.ok(loc=loc, cwd=loc)
        self.assertFalse((self.data / 'active-index.json').exists())

    def test_projects_line_not_repeated(self):
        (self.data / 'projects.txt').write_text(f'# mine\n{self.repo}/../repo\nother\n')
        r = self.ok()
        self.assertEqual((self.data / 'projects.txt').read_text(), f'# mine\n{self.repo}/../repo\nother\n')
        self.assertNotIn('projects.txt', r.stdout)

    def test_slug_gets_suffix_when_folder_exists(self):
        self.ok()
        (self.repo / TASK_DIR / '.active').unlink()
        r = self.ok()
        self.assertIn(f'task: {self.today}-probe-task-b', r.stdout)
        self.assertTrue(self.task_folder(name=f'{self.today}-probe-task-b').is_dir())
        (self.repo / TASK_DIR / '.active').unlink()
        self.assertIn(f'task: {self.today}-probe-task-c', self.ok().stdout)

    def test_task_id_exact(self):
        self.ok('--task-id', '261116-exact', slug=None)
        self.assertTrue(self.task_folder(name='261116-exact').is_dir())

    def test_run_log_kinds_with_statusline(self):
        self.statusline()
        self.ok()
        self.assertEqual(self.kinds(self.task_folder()), ['step', 'cost'])

    def test_run_log_kinds_without_statusline(self):
        self.ok()
        self.assertEqual(self.kinds(self.task_folder()), ['step'])

    def test_mismatch_line_passed_through(self):
        r = self.ok('--model', 'claude-sonnet-4-5')
        mismatch = [x for x in r.stdout.splitlines() if x.startswith('MISMATCH:')]
        self.assertEqual(len(mismatch), 1, r.stdout)
        self.assertIn('claude-sonnet-4-5', mismatch[0])
        self.assertNotIn('MISMATCH', self.ok_stdout_opus())

    def ok_stdout_opus(self):
        (self.repo / TASK_DIR / '.active').unlink()
        return self.ok('--slug', 'opus-task').stdout

    def test_monitor_line_order(self):
        lines = self.ok().stdout.splitlines()
        self.assertEqual([x.split(':')[0] for x in lines], ['task', 'folder', 'monitor', 'written'])

    def test_no_monitor_config_reports_default_and_starts_nothing(self):
        (self.data / 'monitor-config.json').unlink()
        out = dict(line.partition(': ')[::2] for line in self.ok().stdout.splitlines())
        self.assertEqual(out['monitor'], 'not started (autostart off by default; start it with /my-agent:monitor)')
        self.assertFalse((self.data / 'monitor.json').exists())
        self.assertFalse((self.data / 'monitor.log').exists())

    def test_custom_task_dir(self):
        r = run_script(SCRIPT, 'create', '--loc', str(self.repo), '--profile', 'general', '--slug', 'probe-task',
                       '--request=x', '--model', NAME, '--cwd', str(self.repo), '--data-dir', str(self.data),
                       '--task-dir', 'docs/agent', env=self.env, cwd=self.root, drop=self.drop)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.repo / 'docs' / 'agent' / '.active').is_file())
        self.assertEqual(self.kinds(self.repo / 'docs' / 'agent' / f'{self.today}-probe-task'), ['step'])


class WorkBranchTest(CreateBase):
    """`work-branch`: `git switch -c my-agent-task/<id>` with the ID `create` would make (criterion 13)."""

    def branch_call(self, repo, slug='probe-task'):
        return run_script(SCRIPT, 'work-branch', '--loc', str(repo), '--slug', slug, '--data-dir', str(self.data),
                          '--task-dir', TASK_DIR, env=self.env, cwd=self.root, drop=self.drop)

    def head(self, repo):
        return git(repo, 'rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()

    def sha(self, repo):
        return git(repo, 'rev-parse', '--short', 'HEAD').stdout.strip()

    def switched(self, repo, name='main'):
        before = self.sha(repo)
        r = self.branch_call(repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        branch = f'my-agent-task/{self.today}-probe-task'
        self.assertEqual(r.stdout.strip(), f'work-branch: switched to {branch} (from {before})')
        self.assertEqual(self.head(repo), branch)
        self.assertEqual(self.sha(repo), before)
        self.assertEqual(git(repo, 'branch', '--list', name).stdout.strip().lstrip('* '), name)   # the old branch stays
        return branch

    def test_main_switches_and_keeps_uncommitted_change(self):
        repo = init_repo(self.root / 'm', branch='main')
        (repo / 'f.txt').write_text('changed')
        self.switched(repo, 'main')
        self.assertEqual((repo / 'f.txt').read_text(), 'changed')
        self.assertIn('f.txt', git(repo, 'status', '--porcelain').stdout)

    def test_master_switches(self):
        self.switched(init_repo(self.root / 'ms', branch='master'), 'master')

    def test_detached_head_switches(self):
        repo = init_repo(self.root / 'd', branch='main')
        git(repo, 'checkout', '-q', '--detach')
        self.switched(repo, 'main')

    def test_id_gets_suffix_when_folder_exists(self):
        repo = init_repo(self.root / 's', branch='main')
        (repo / TASK_DIR / f'{self.today}-probe-task').mkdir(parents=True)
        r = self.branch_call(repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f'switched to my-agent-task/{self.today}-probe-task-b (from ', r.stdout)

    def test_existing_branch_is_not_switched_over(self):
        repo = init_repo(self.root / 'e', branch='main')
        branch = f'my-agent-task/{self.today}-probe-task'
        git(repo, 'branch', branch)
        sha = git(repo, 'rev-parse', branch).stdout
        r = self.branch_call(repo)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip(), f'work-branch: not switched: branch {branch} exists')
        self.assertEqual(self.head(repo), 'main')
        self.assertEqual(git(repo, 'rev-parse', branch).stdout, sha)

    def test_git_refusal_prints_first_stderr_line(self):
        repo = init_repo(self.root / 'r', branch='main')
        git(repo, 'branch', 'my-agent-task')
        sha = self.sha(repo)
        r = self.branch_call(repo)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        line = r.stdout.strip()
        self.assertTrue(line.startswith('work-branch: not switched: '), line)
        self.assertEqual(len(line.splitlines()), 1)
        self.assertIn('my-agent-task', line)
        self.assertEqual((self.head(repo), self.sha(repo)), ('main', sha))

    def test_create_with_the_printed_id(self):
        repo = init_repo(self.root / 'c', branch='main')
        r = self.branch_call(repo)
        task = r.stdout.split('my-agent-task/')[1].split(' ')[0]
        self.ok('--task-id', task, slug=None, loc=repo, cwd=repo)
        self.assertTrue((repo / TASK_DIR / task).is_dir())

    def test_bad_arguments_are_exit_2(self):
        repo = init_repo(self.root / 'b', branch='main')
        for bad in ('Bad Slug', 'x' * 31):
            self.assertEqual(self.branch_call(repo, bad).returncode, 2)
        self.assertEqual(self.branch_call(self.root / 'missing').returncode, 2)
        self.assertEqual(self.head(repo), 'main')


class RequestTextTest(CreateBase):
    def check(self, text):
        r = self.ok(f'--request={text}')
        got = self.intake(self.task_folder())['Request']
        self.assertEqual(got, text)
        self.assertIn(f'Request: {text}\n', (self.task_folder() / 'intake.md').read_text(encoding='utf-8'))
        return r

    def test_starts_with_dashes(self):
        self.check('--general standard 5 intake')

    def test_single_quote(self):
        self.check("it's done")

    def test_backtick_semicolon_pipe(self):
        self.check('run `ls`; then | stop')

    def test_dollar_and_non_ascii_and_edge_spaces(self):
        self.check('$(x) --general 작업 해  ')

    def test_not_shlex_split(self):
        self.check('say "hi" and \\ done')


class RequestFileTest(CreateBase):
    def create_from(self, *request_args, slug='probe-task'):
        base = ['--loc', str(self.repo), '--profile', 'general', '--model', NAME, '--slug', slug]
        return run_script(SCRIPT, 'create', *base, *request_args, '--cwd', str(self.repo), '--data-dir', str(self.data),
                          '--task-dir', TASK_DIR, env=self.env, cwd=self.root, drop=self.drop)

    def request_file(self, data, name='request.txt'):
        path = self.root / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))
        return path

    def refused(self, *request_args):
        before = snapshot(self.root)
        r = self.create_from(*request_args)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('nothing written', r.stderr)
        self.assertEqual(snapshot(self.root), before)
        return r

    def test_create_request_file(self):
        hook_skip = 'git commit ' + '--no' + '-verify'   # text the deny list refuses, so it cannot ride on a command line
        text = f'Check the rule for `{hook_skip}` and $(x); a | b \'quoted\' "too" 작업'
        for ending in ('', '\n', '\r\n'):
            with self.subTest(ending=ending):
                path = self.request_file(text + ending)
                r = self.create_from('--request-file', str(path), slug='from-file' + ('' if not ending else str(len(ending))))
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                folder = self.task_folder(name=f'{self.today}-from-file' + ('' if not ending else str(len(ending))))
                self.assertEqual(self.intake(folder)['Request'], text)
                self.assertIn(f'Request: {text}\n', (folder / 'intake.md').read_text(encoding='utf-8'))
                (self.repo / TASK_DIR / '.active').unlink()

    def test_create_request_file_missing_or_empty_is_refused(self):
        missing = self.root / 'missing.txt'
        r = self.refused('--request-file', str(missing))
        self.assertIn(f'--request-file: no such file {missing}', r.stderr)
        for data in ('', '\n', '\r\n', '  \n'):
            with self.subTest(data=data):
                r = self.refused('--request-file', str(self.request_file(data)))
                self.assertIn('--request=<line> is needed and must not be empty', r.stderr)

    def test_create_request_file_multiline_is_refused(self):
        r = self.refused('--request-file', str(self.request_file('first line\nsecond line\n')))
        self.assertIn('--request must be one line', r.stderr)
        self.refused('--request-file', str(self.request_file('first\n\n')))

    def test_create_request_and_request_file_together_is_refused(self):
        path = self.request_file('do it\n')
        self.refused('--request=do it', '--request-file', str(path))
        r = self.refused()   # neither
        self.assertIn('--request', r.stderr)


class RefuseTest(CreateBase):
    def assertRefused(self, code, *args, **kw):
        before_repo = snapshot(self.root)
        r = self.create(*args, **kw)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        self.assertIn('nothing written', r.stderr)
        self.assertEqual(r.stdout, '')
        self.assertEqual(snapshot(self.root), before_repo)
        return r

    def test_active_exists(self):
        (self.repo / TASK_DIR).mkdir()
        (self.repo / TASK_DIR / '.active').write_text('task: 261115-other\nphase: 2\nsession: \nstarted: t\n')
        r = self.assertRefused(1)
        self.assertIn('.active exists (task 261115-other)', r.stderr)

    def test_broken_active_also_refuses(self):
        (self.repo / TASK_DIR).mkdir()
        (self.repo / TASK_DIR / '.active').write_text('phase: 2\n')
        self.assertRefused(1)

    def test_task_id_folder_exists(self):
        (self.repo / TASK_DIR / '261116-x').mkdir(parents=True)
        r = self.assertRefused(1, '--task-id', '261116-x', slug=None)
        self.assertIn('exists; nothing written', r.stderr)

    def test_invalid_arguments(self):
        (self.root / 'plain').mkdir()
        gi = init_repo(self.root / 'gi')
        (gi / TASK_DIR).mkdir()
        (gi / TASK_DIR / '.gitignore').write_text('*\n')
        cases = {
            'bad profile': ['--profile', 'Dev'],
            'bad slug upper': ['--slug', 'Bad_Slug'],
            'bad slug long': ['--slug', 'a' * 31],
            'empty slug': ['--slug', ''],
            'both slug and id': ['--task-id', '261116-x'],
            'empty request': ['--request='],
            'blank request': ['--request=   '],
            'newline request': ['--request=a\nb'],
            'unknown preset': ['--preset', 'nope'],
            'router pick equal': ['--router-pick', 'general'],
            'router pick bad': ['--router-pick', 'x'],
            'dev outside git': ['--profile', 'dev', '--loc', str(self.root / 'plain')],
            'gitignore outside git': ['--gitignore', 'ignore', '--loc', str(self.root / 'plain')],
            'gitignore exists': ['--gitignore', 'ignore', '--loc', str(gi)],
            'bad gitignore choice': ['--gitignore', 'maybe'],
            'ask without rec': ['--ask', 'gate=Q q=x'],
            'ask q dashes': ['--ask', 'gate=Q q=--dev rec=x'],
            'ask not key=value': ['--ask', 'gate=Q q=x rec=y nonsense'],
            'ask unbalanced': ['--ask', 'gate=Q q="x rec=y'],
            'answer without choice': ['--answer', 'gate=Q'],
            'relative loc': ['--loc', 'repo'],
            'missing loc': ['--loc', str(self.root / 'nowhere')],
            'bad follows': ['--follows', 'a b'],
            'empty model': ['--model', ''],
        }
        for name, extra in cases.items():
            with self.subTest(name):
                self.assertRefused(2, *extra)

    def test_neither_slug_nor_task_id(self):
        self.assertRefused(2, slug=None)

    def test_missing_required_arguments(self):
        for args in (['--profile', 'general'], ['--loc', str(self.repo)]):
            r = run_script(SCRIPT, 'create', *args, '--data-dir', str(self.data), env=self.env, cwd=self.root,
                           drop=self.drop)
            self.assertEqual(r.returncode, 2)

    def test_broken_index_when_a_line_is_needed(self):
        loc = self.root / 'drafts'
        loc.mkdir()
        run = self.root / 'notes'
        run.mkdir()
        for text in ('{not json', '[1, 2]'):
            (self.data / 'active-index.json').write_text(text)
            with self.subTest(text):
                self.assertRefused(2, loc=loc, cwd=run)

    def test_broken_index_ignored_when_no_line_needed(self):
        (self.data / 'active-index.json').write_text('{not json')
        self.ok()

    def test_unknown_preset_when_preset_file_invalid(self):
        self.write_models({'dev': {'fast': {'planner': {'model': 'haiku'}}}})
        self.assertRefused(2, '--preset', 'fast')


class StopAfterWriteTest(CreateBase):
    def test_run_log_path_is_a_folder(self):
        # the run-log is created by run-log.py; a folder in its place makes the step call fail
        folder = self.task_folder()
        script = self.root / 'wrap.py'
        script.write_text(
            'import runpy, sys, pathlib\n'
            'real = pathlib.Path.mkdir\n'
            'def mk(self, *a, **k):\n'
            '    real(self, *a, **k)\n'
            '    if self.name == "%s-probe-task" and not (self / "run-log.md").exists():\n'
            '        (self / "run-log.md").mkdir()\n'
            'pathlib.Path.mkdir = mk\n'
            'sys.argv = [sys.argv[1]] + sys.argv[2:]\n'
            'runpy.run_path(sys.argv[0], run_name="__main__")\n' % self.today)
        r = subprocess.run([sys.executable, str(script), str(SCRIPT), 'create', '--loc', str(self.repo), '--profile',
                            'general', '--slug', 'probe-task', '--request=x', '--model', NAME, '--cwd', str(self.repo),
                            '--data-dir', str(self.data), '--task-dir', TASK_DIR],
                           capture_output=True, text=True, timeout=30,
                           env={k: v for k, v in dict(os.environ, **self.env).items() if k not in self.drop})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn('intake: stopped at run-log step:', r.stderr)
        written = r.stderr.partition('written: ')[2]
        for name in ('task folder', '.active', 'intake.md', 'projects.txt line'):
            self.assertIn(name, written)
        self.assertTrue((self.repo / TASK_DIR / '.active').is_file())
        self.assertTrue((folder / 'intake.md').is_file())
        self.assertEqual(r.stdout, '')

    def test_data_folder_failure_names_the_data_folder(self):
        # a file in place of the data folder's parent: its mkdir fails, and the stage must not say `.active`
        blocker = self.root / 'blocker'
        blocker.write_text('x', encoding='utf-8')
        r = self.create(env={'MA_DATA_DIR': str(blocker / 'data')})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn('intake: stopped at data folder:', r.stderr)
        self.assertNotIn('stopped at .active', r.stderr)


class RoundTripTest(CreateBase):
    def make(self, loc=None, cwd=None, *args):
        r = self.ok(*args, loc=loc, cwd=cwd)
        return r, self.task_folder(loc)

    def test_active_readers(self):
        import ma_active
        _, folder = self.make()
        with clean_task_env():
            a = ma_active.read_active(self.repo)
            self.assertEqual((a.task, a.phase, a.session), (folder.name, '1', 's-1'))
            self.assertRegex(a.started, r'^\d{4}-\d\d-\d\d \d\d:\d\d$')
            self.assertEqual(a.task_dir, folder)
            f = ma_active.find_active(str(self.repo), self.data)
            self.assertEqual(f.task, folder.name)

    def test_find_active_through_index_outside_git(self):
        import ma_active
        loc = self.root / 'drafts'
        loc.mkdir()
        run = self.root / 'notes'
        (run / 'sub').mkdir(parents=True)
        _, folder = self.make(loc=loc, cwd=run)
        with clean_task_env():
            for start in (run, run / 'sub'):
                f = ma_active.find_active(str(start), self.data)
                self.assertIsNotNone(f, start)
                self.assertEqual((f.task, f.phase), (folder.name, '1'))
        r = run_script(L4 / 'scripts' / 'run-log.py', 'ask', 'gate=Q', 'q=again', '--cwd', str(run),
                       '--data-dir', str(self.data), env=self.env, drop=self.drop)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_later_run_log_call_finds_the_task(self):
        _, folder = self.make()
        r = run_script(L4 / 'scripts' / 'run-log.py', 'ask', 'gate=Q', 'q=next', 'rec=x', '--cwd', str(self.repo),
                       '--data-dir', str(self.data), env=self.env, drop=self.drop)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.kinds(folder), ['step', 'ask'])

    def test_plan_approved_check(self):
        _, folder = self.make()
        env = dict(CLAUDE_HOOK_ENV, MA_DATA_DIR=str(self.data), MA_GATE_REPORT_DIR=str(self.root / 'gr'),
                   CLAUDE_CODE_SESSION_ID='s-1')

        def hook(path):
            payload = {'hook_event_name': 'PreToolUse', 'tool_name': 'Write', 'tool_input': {'file_path': str(path)},
                       'session_id': 's-1'}
            return run_hook('plan-approved-check.py', None, payload, self.repo, env=env, drop=KEEP)

        r = hook(self.repo / 'src' / 'a.py')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['hookSpecificOutput']['permissionDecision'], 'ask')
        r = hook(folder / 'plan.md')
        self.assertEqual((r.returncode, r.stdout), (0, ''))

    def test_monitor_readers(self):
        from monitor.mdfiles import read_intake
        from monitor.registry import Registry
        from monitor.runlog import read_lines
        self.statusline()
        self.write_models({'general': {'standard': {}}})
        _, folder = self.make(None, None, '--request=my request', '--auto', '--preset', 'standard',
                              '--ask', 'gate=Q q=x rec=y', '--answer', 'gate=Q choice=y')
        d = read_intake(folder / 'intake.md')
        self.assertEqual((d['status'], d['profile'], d['title']), ('active', 'general', 'my request'))
        lines = read_lines(folder / 'run-log.md')
        self.assertEqual(len(lines), len(log_lines(folder)))
        self.assertEqual(len(lines), 6)
        self.assertIsNotNone(events(folder))
        with clean_task_env():
            tasks = Registry(projects_file=self.data / 'projects.txt', claude_root=self.root / 'projects',
                             prices_file=self.root / 'prices.json').list_tasks()
        self.assertEqual([t['id'] for t in tasks], [folder.name])
        self.assertEqual(tasks[0]['profile'], 'general')

    def test_archive_works(self):
        _, folder = self.make()
        r = run_script(L4 / 'scripts' / 'archive.py', '--task', str(folder), '--name', 'probe')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((folder / r.stdout.strip() / 'intake.md').is_file())

    def test_intake_md_head_and_plugin_value(self):
        _, folder = self.make()
        text = (folder / 'intake.md').read_text(encoding='utf-8')
        self.assertTrue(text.startswith('Status: active\n'))
        head, _ = self.parsed(self.repo)
        self.assertEqual(self.intake(folder)['my-agent'], head['plugin'])

    def test_facts_after_create_sees_the_task(self):
        _, folder = self.make()
        _, cands = self.parsed(self.repo)
        self.assertTrue(cands[0]['active'].startswith(f'{folder.name} phase 1 session s-1 started '))
        self.assertEqual((cands[0]['ids'], cands[0]['listed']), (folder.name, 'yes'))


if __name__ == '__main__':
    unittest.main()
