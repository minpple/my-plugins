"""tools/build-docs.py: the GitHub Pages architecture page (docs/architecture.html) matches the plugin files."""
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / 'tools' / 'build-docs.py'
spec = importlib.util.spec_from_file_location('build_docs', SCRIPT)
bd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bd)


def page_data(page: str) -> dict:
    raw = page.split('const D = ', 1)[1].split(';\nconst $', 1)[0]
    return json.loads(raw.replace('<\\/', '</'))


class BuildDocsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = bd.build()
        cls.data = page_data(cls.page)

    def test_committed_page_is_current(self):
        r = subprocess.run([sys.executable, str(SCRIPT), '--check'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_output_is_architecture_page(self):
        self.assertEqual(bd.OUT, bd.REPO / 'docs' / 'architecture.html')
        r = subprocess.run([sys.executable, str(SCRIPT), '--check'], capture_output=True, text=True)
        self.assertIn('docs/architecture.html', r.stdout)

    def test_pre_commit_hook_names_architecture_page(self):
        hook = (REPO / '.githooks' / 'pre-commit').read_text(encoding='utf-8')
        self.assertIn('docs/architecture.html', hook)
        self.assertNotIn('docs/index.html', hook)

    def test_every_manifest_agent_is_on_the_page(self):
        manifest = json.loads((bd.PLUGIN / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))
        names = {Path(p).stem for p in manifest['agents']}
        self.assertEqual({a['id'] for a in self.data['agents']}, names)
        on_levels = {c['id'] for l in self.data['levels'] for c in l['comps']}
        self.assertLessEqual(names, on_levels)

    def test_artifact_list_matches_the_file_layout(self):
        tree = {name for name, _ in bd.tree_files(bd.read(bd.ARCH))}
        self.assertEqual({a[0] for a in bd.ARTIFACTS}, tree)

    def test_four_levels_eight_steps_five_gates(self):
        self.assertEqual([l['id'] for l in self.data['levels']], ['L1', 'L2', 'L3', 'L4'])
        self.assertEqual([s['n'] for s in self.data['steps']], list('12345678'))
        self.assertEqual([g['id'] for g in self.data['gates']], ['G1-A', 'G1-B', 'G2', 'G3', 'E'])

    def test_step_rules_carry_step_ids(self):
        import re
        titles = [r['title'] for s in self.data['steps'] for r in s['rules']]
        self.assertEqual([t for t in titles if re.match(r'\d[a-z]?\. ', t) or 'step 1,' in t], [])
        for title in ('Intake (step 1A, Router)', '1B Explore → Scope', 'Background research', '2A Plan', '2B Plan Review',
                      'G1-B plan approval', '3A Execute', '3B Merge', '4A Verify', '4B Review → Deliver'):
            self.assertIn(title, titles)
        self.assertNotIn('"7. Verify"', self.page)

    def test_unit_copy_rules_are_on_the_page(self):
        by_step = {s['n']: s for s in self.data['steps']}
        text5 = ' '.join(r['from'] + r['title'] for r in by_step['5']['rules'])
        text6 = ' '.join(r['from'] + r['title'] for r in by_step['6']['rules'])
        self.assertIn('unit-copies.md', text5)
        self.assertIn('unit-copies.md', text6)
        self.assertIn('While units run', text5)

    def test_check_script_and_lib_are_on_the_page(self):
        self.assertIn('check-commands.py', self.page)
        self.assertIn('ma_checks.py', self.page)
        self.assertIn('check-commands.py', [s['name'] for s in self.data['l4']['scripts']])
        self.assertIn('ma_checks.py', [s['name'] for s in self.data['l4']['lib']])

    def test_scope_comes_from_scope_guard(self):
        coder = next(a for a in self.data['agents'] if a['id'] == 'coder')
        self.assertTrue(coder['scope']['bashWrites'])
        self.assertIn('<task location>/<task_dir>', coder['scope']['denyWrite'])
        gate = next(a for a in self.data['agents'] if a['id'] == 'gate-analyst')
        self.assertEqual(gate['scope']['write'], ['<task folder>/gate-report.md'])

    def test_scope_has_no_machine_paths(self):
        for a in self.data['agents']:
            for key in ('read', 'write', 'denyWrite'):
                for path in a['scope'][key]:
                    self.assertNotIn('/Users/', path, a['id'])
                    self.assertNotIn('/private/', path, a['id'])
            if a['id'] == 'gate-analyst':
                self.assertEqual(a['scope']['read'], ['<task folder>/gate-tally.md', '<task folder>/gate-report.md'])
            else:
                for root in ('<task location>', '<data folder>', '<plugin folder>'):
                    self.assertIn(root, a['scope']['read'], a['id'])

    def test_missing_heading_stops_the_build(self):
        with self.assertRaises(bd.SourceError):
            bd.cut('# a\n## b\ntext\n', 'no such heading')

    def test_cut_skips_headings_inside_fences(self):
        text = '## Format\n```text\n# Title\n## Summary\n```\nafter\n## Next\n'
        self.assertIn('after', bd.cut(text, 'Format'))

    def test_markdown_subset(self):
        out = bd.md('| A | B |\n|---|---|\n| `x \\| y` | **b** |\n\n- one\n  - two\n\n```text\n<tag>\n```')
        self.assertIn('<code>x | y</code>', out)
        self.assertIn('<strong>b</strong>', out)
        self.assertIn('<ul><li>one<ul><li>two</li></ul></li></ul>', out)
        self.assertIn('&lt;tag&gt;', out)

    def test_page_has_no_script_breakout(self):
        payload = self.page.split('const D = ', 1)[1].split(';\nconst $', 1)[0]
        self.assertNotIn('</script', payload)

    def test_template_step_letters(self):
        import re
        tpl = (REPO / 'tools' / 'docs-template.html').read_text(encoding='utf-8')
        m = re.search(r'const STEP_CODE = (\{[^}]*\});', tpl)
        self.assertIsNotNone(m)
        table = dict(re.findall(r"'(\d)'\s*:\s*'(\w+)'", m.group(1)))
        self.assertEqual(table, {'1': '1A', '2': '1B', '3': '2A', '4': '2B',
                                 '5': '3A', '6': '3B', '7': '4A', '8': '4B'})
        for gone in ('<b>${s.n}</b>', '`${n}. ${', 'Step ${s.n} ·'):
            self.assertNotIn(gone, tpl)
        for kept in ('#flow/${s.n}', 'id="step-${s.n}"'):
            self.assertIn(kept, tpl)

    def test_no_old_gate_names(self):
        import re
        page = self.page.replace('G1a G1-A · G1b G1-B', '').replace('(old logs: G1b)', '')
        self.assertIsNone(re.search(r'G1[ab]\b', page))


if __name__ == '__main__':
    unittest.main()
