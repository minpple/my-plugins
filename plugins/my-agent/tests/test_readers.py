"""ma_readers: the reader finder for docs-only check rounds (which unittest files read a changed document).

This file passes documents to the finder as repo-relative strings only. It builds no root-joined path to a document
and no root-joined path with a variable tail, so the finder never selects it for a document.
"""
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (puts the L4 lib on sys.path)
import ma_readers as mr

LOC = Path(__file__).resolve().parents[3]       # the repository root (the task location)

SUITE = 'cd plugins/my-agent && python3 -m unittest discover -s tests'
MONITOR = 'cd plugins/my-agent/monitor && python3 -m unittest discover tests'
ROOTSUITE = 'python3 -m unittest discover -s tests'
TRAY = 'cd plugins/my-agent-tray && python3 -m unittest discover -s tests'
ARCH = 'plugins/my-agent/docs/build-guide/my-agent-architecture.md'


def readers(command, documents):
    """Names of the files `command` covers that read any of `documents`, or None for an unrecognised command."""
    covered = mr.covered_files(command, LOC)
    if covered is None:
        return None
    return sorted(f.name for f in mr.reading_tests(covered, documents, LOC))


class IsDocument(unittest.TestCase):
    def test_documents(self):
        for p in ('docs/index.html', 'docs/blueprint/decisions.md', 'docs/.nojekyll',
                  'plugins/my-agent/docs/build-guide/my-agent-architecture.md',
                  'plugins/my-agent/docs/agent-models.example.json'):
            self.assertTrue(mr.is_document(p), p)

    def test_not_documents(self):
        for p in ('README.md', 'CLAUDE.md', 'docs', 'docs.md', 'tools/docs-template.html',
                  'plugins/my-agent/monitor/tests/fixtures/report/project/docs/agent/x.md',
                  'plugins/my-agent/tests/judge-fixtures/x/docs/a.md', 'tests/docs/a.md'):
            self.assertFalse(mr.is_document(p), p)


class ParseDiscover(unittest.TestCase):
    def test_repository_commands(self):
        p = mr.parse_discover(SUITE)
        self.assertEqual((p['cd'], p['start'], p['pattern']), ('plugins/my-agent', 'tests', 'test*.py'))
        p = mr.parse_discover(MONITOR)
        self.assertEqual((p['cd'], p['start'], p['pattern']), ('plugins/my-agent/monitor', 'tests', 'test*.py'))
        p = mr.parse_discover(ROOTSUITE)
        self.assertEqual((p['cd'], p['start'], p['pattern']), (None, 'tests', 'test*.py'))
        p = mr.parse_discover(TRAY)
        self.assertEqual((p['cd'], p['start']), ('plugins/my-agent-tray', 'tests'))

    def test_halves_and_options(self):
        p = mr.parse_discover(SUITE + " -p 'test_[a-h]*.py'")
        self.assertEqual(p['pattern'], 'test_[a-h]*.py')
        self.assertEqual(p['tokens'], ['-s', 'tests', '-p', 'test_[a-h]*.py'])
        p = mr.parse_discover('python -m unittest discover --start-directory t --pattern=x_*.py -v -k name')
        self.assertEqual((p['start'], p['pattern']), ('t', 'x_*.py'))
        p = mr.parse_discover('python3 -m unittest discover')
        self.assertEqual((p['start'], p['pattern']), ('.', 'test*.py'))
        p = mr.parse_discover('python3 -m unittest discover tests check_*.py')
        self.assertEqual((p['start'], p['pattern']), ('tests', 'check_*.py'))
        self.assertEqual(mr.parse_discover('python3 -m unittest discover -s tests -t . -b -f -c -q')['start'], 'tests')

    def test_not_recognised(self):
        for c in (SUITE + ' | tail -3', SUITE + '; ls', SUITE + ' || true', 'FOO=1 ' + SUITE,
                  'python3 -m pytest tests', SUITE + ' --unknown', SUITE + ' && ls', 'python3 -m unittest tests.x',
                  'cd plugins/my-agent python3 -m unittest discover', 'python3 -m unittest discover -s',
                  'python3 -m unittest discover a b c d', SUITE + ' > out.txt', ''):
            self.assertIsNone(mr.parse_discover(c), c)


class Covered(unittest.TestCase):
    def test_pattern_and_packages(self):
        with tempfile.TemporaryDirectory() as t:
            top = Path(t).resolve()
            (top / 'p' / 'tests' / 'sub').mkdir(parents=True)
            (top / 'p' / 'tests' / 'loose').mkdir()
            (top / 'p' / 'tests' / 'test_a.py').write_text('')
            (top / 'p' / 'tests' / 'check_b.py').write_text('')
            (top / 'p' / 'tests' / 'helpers.py').write_text('')
            (top / 'p' / 'tests' / 'sub' / '__init__.py').write_text('')
            (top / 'p' / 'tests' / 'sub' / 'test_c.py').write_text('')
            (top / 'p' / 'tests' / 'loose' / 'test_d.py').write_text('')
            names = lambda c: sorted(f.name for f in mr.covered_files(c, top))   # noqa: E731
            self.assertEqual(names('cd p && python3 -m unittest discover -s tests'), ['test_a.py', 'test_c.py'])
            self.assertEqual(names("cd p && python3 -m unittest discover -s tests -p 'check_*.py'"), ['check_b.py'])
            self.assertEqual(names('cd p/tests && python3 -m unittest discover'), ['test_a.py', 'test_c.py'])
            self.assertIsNone(mr.covered_files('cd p && python3 -m unittest discover -s nope', top))
            self.assertIsNone(mr.covered_files('pytest p', top))


class Narrowed(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(mr.narrowed_command(SUITE, ['test_arch_doc.py']), SUITE + ' -p test_arch_doc.py')
        self.assertEqual(mr.narrowed_command(SUITE, [Path('x/test_a.py'), Path('x/test_b.py')]),
                         'cd plugins/my-agent && python3 -m unittest discover -s tests -p test_a.py'
                         ' && python3 -m unittest discover -s tests -p test_b.py')
        self.assertEqual(mr.narrowed_command(SUITE + " -p 'test_[a-h]*.py'", ['test_arch_doc.py']),
                         SUITE + ' -p test_arch_doc.py')
        self.assertEqual(mr.narrowed_command(MONITOR, ['test_report.py']),
                         'cd plugins/my-agent/monitor && python3 -m unittest discover tests -p test_report.py')
        self.assertEqual(mr.narrowed_command(ROOTSUITE, ['test_a.py']), ROOTSUITE + ' -p test_a.py')
        self.assertEqual(mr.narrowed_command('python3 -m unittest discover tests check_*.py -v', ['check_g.py']),
                         'python3 -m unittest discover tests -v -p check_g.py')
        self.assertEqual(mr.narrowed_command('python3 -m unittest discover tests x_*.py .', ['x_a.py']),
                         'python3 -m unittest discover tests -t . -p x_a.py')

    def test_quoting(self):
        self.assertEqual(mr.narrowed_command(ROOTSUITE, ['test a b.py']), ROOTSUITE + " -p 'test a b.py'")

    def test_unrecognised_stays(self):
        self.assertEqual(mr.narrowed_command('pytest tests', ['test_a.py']), 'pytest tests')


class RealSources(unittest.TestCase):
    """Criterion 3: the reader sets of this repository, from the real test sources."""

    def test_blueprint_documents_have_no_reader(self):
        docs = ['docs/blueprint/decisions.md', 'docs/blueprint/features.md', 'docs/blueprint/backlog.md']
        for c in (SUITE, MONITOR, ROOTSUITE, TRAY):
            self.assertEqual(readers(c, docs), [], c)

    def test_architecture_document(self):
        self.assertEqual(readers(SUITE, [ARCH]), ['test_agents.py', 'test_arch_doc.py', 'test_blueprint.py'])
        self.assertEqual(readers(ROOTSUITE, [ARCH]), ['test_build_docs.py'])
        self.assertEqual(readers(MONITOR, [ARCH]), [])
        self.assertEqual(readers(TRAY, [ARCH]), [])

    def test_feature_pages(self):
        for doc in ('docs/index.html', 'docs/index-ko.html'):
            self.assertEqual(readers(ROOTSUITE, [doc]), ['test_feature_pages.py', 'test_step_labels.py'], doc)
            for c in (SUITE, MONITOR, TRAY):
                self.assertEqual(readers(c, [doc]), [], (c, doc))

    def test_fixture_documents_are_not_documents(self):
        self.assertFalse(mr.is_document('plugins/my-agent/monitor/tests/fixtures/report/project/docs/agent/x.md'))

    def test_plugin_suite_halves(self):
        first = SUITE + " -p 'test_[a-h]*.py'"
        second = SUITE + " -p 'test_[i-z]*.py'"
        self.assertEqual(readers(first, [ARCH]), ['test_agents.py', 'test_arch_doc.py', 'test_blueprint.py'])
        self.assertEqual(readers(second, [ARCH]), [])

    def test_this_file_is_not_selected(self):
        docs = [ARCH, 'docs/index.html', 'docs/index-ko.html', 'docs/blueprint/decisions.md', 'docs/architecture.html']
        self.assertEqual(mr.reading_tests([Path(__file__)], docs, LOC), {})


class TempProjects(unittest.TestCase):
    """Rules 1-5 on small projects."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.top = Path(tmp.name).resolve()
        (self.top / 'tests').mkdir()
        (self.top / 'tools').mkdir()
        (self.top / 'docs').mkdir()
        for d in ('guide.md', 'other.md'):
            (self.top / 'docs' / d).write_text('x')

    def add(self, name, source, folder='tests'):
        f = self.top / folder / name
        f.write_text(source, encoding='utf-8')
        return f

    def find(self, documents=('docs/guide.md',)):
        files = sorted((self.top / 'tests').glob('test_*.py'))
        return sorted(f.name for f in mr.reading_tests(files, list(documents), self.top))

    def test_concrete_chain(self):
        self.add('test_a.py', "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n"
                              "X = ROOT / 'docs' / 'guide.md'\n")
        self.add('test_b.py', "from pathlib import Path\nROOT = Path(__file__).parent.parent\n"
                              "X = ROOT.joinpath('docs', 'other.md')\n")
        self.add('test_c.py', "from pathlib import Path\nROOT = Path(__file__).resolve().parent.parent\n"
                              "X = ROOT.joinpath('docs/guide.md')\nY = X.with_name('other.md')\n")
        self.assertEqual(self.find(), ['test_a.py', 'test_c.py'])
        self.assertEqual(self.find(['docs/other.md']), ['test_b.py', 'test_c.py'])

    def test_function_local_derived_root(self):
        self.add('test_a.py', "from pathlib import Path\n\ndef t():\n"
                              "    d = Path(__file__).resolve().parents[1] / 'docs'\n"
                              "    return (d / 'guide.md').read_text()\n")
        self.assertEqual(self.find(), ['test_a.py'])

    def test_variable_tail_with_constant(self):
        self.add('test_a.py', "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n\n"
                              "def read(n):\n    return (ROOT / 'docs' / n).read_text()\n\nread('guide.md')\n")
        self.add('test_b.py', "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n\n"
                              "def read(n):\n    return (ROOT / 'docs' / n).read_text()\n\nread(compute())\n")
        self.add('test_c.py', "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n"
                              "FILES = ['docs/guide.md', 'x']\nfor f in FILES:\n    (ROOT / f).read_text()\n")
        self.assertEqual(self.find(), ['test_a.py', 'test_c.py'])

    def test_joinpath_helper_with_segments(self):
        self.add('test_a.py', "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n\n"
                              "class T:\n    def text(self, *parts):\n        return ROOT.joinpath(*parts).read_text()\n"
                              "    def test(self):\n        self.text('docs', 'guide.md')\n")
        self.add('test_b.py', "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n\n"
                              "def text(*parts):\n    return ROOT.joinpath(*parts).read_text()\n\ntext('docs', 'x.md')\n")
        self.assertEqual(self.find(), ['test_a.py'])

    def test_imported_root(self):
        self.add('helpers.py', "from pathlib import Path\nREPO = Path(__file__).resolve().parents[1]\n")
        self.add('test_a.py', "from helpers import REPO\nX = REPO / 'docs' / 'guide.md'\n")
        self.add('test_b.py', "import helpers\nX = helpers.REPO / 'docs' / 'guide.md'\n")
        self.add('test_c.py', "import helpers as h\nX = h.REPO.joinpath('docs', 'guide.md')\n")
        self.add('test_d.py', "from helpers import REPO\nX = REPO / 'docs' / 'other.md'\n")
        self.assertEqual(self.find(), ['test_a.py', 'test_b.py', 'test_c.py'])

    def test_generator_hop(self):
        self.add('gen.py', "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n"
                           "DOC = ROOT / 'docs' / 'guide.md'\nB = ROOT / 'tools' / 'deep.py'\n", 'tools')
        self.add('deep.py', "from pathlib import Path\nX = Path(__file__).resolve().parents[1] / 'docs' / 'other.md'\n",
                 'tools')
        self.add('test_a.py', "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n"
                              "SCRIPT = ROOT / 'tools' / 'gen.py'\n")
        self.assertEqual(self.find(), ['test_a.py'])
        self.assertEqual(self.find(['docs/other.md']), [])        # one hop only

    def test_hop_skips_a_covered_test_file(self):
        self.add('test_other.py', "from pathlib import Path\nX = Path(__file__).resolve().parents[1] / 'docs' / 'guide.md'\n")
        self.add('test_a.py', "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n"
                              "S = ROOT / 'tests' / 'test_other.py'\n")
        self.assertEqual(self.find(), ['test_other.py'])

    def test_negatives(self):
        self.add('test_a.py', "def t(self):\n    self.assertNotIn('docs/guide.md', hook)\n    x = 'docs/guide.md'\n")
        self.add('test_b.py', "import tempfile\nfrom pathlib import Path\n"
                              "root = Path(tempfile.mkdtemp())\nX = root / 'docs' / 'guide.md'\n")
        self.add('test_c.py', "import importlib\nbd = importlib.import_module('bd')\nX = bd.REPO / 'docs' / 'guide.md'\n")
        self.add('test_d.py', "def t(self):\n    return self.L / 'docs' / 'guide.md'\n")
        self.add('test_e.py', "this is ( not python\ndocs/guide.md\n")
        self.add('test_f.py', "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n\n"
                              "def f(ROOT):\n    return ROOT / 'docs' / 'guide.md'\n")
        self.add('test_g.py', "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\nROOT = make()\n"
                              "X = ROOT / 'docs' / 'guide.md'\n")
        self.add('test_h.py', "from os.path import join\nX = join('docs', 'guide.md')\n")
        self.assertEqual(self.find(), [])

    def test_hop_file_with_syntax_error_reads_nothing(self):
        self.add('gen.py', "def (\n", 'tools')
        self.add('test_a.py', "from pathlib import Path\nS = Path(__file__).resolve().parents[1] / 'tools' / 'gen.py'\n")
        self.assertEqual(self.find(), [])

    def test_deleted_and_renamed_documents(self):
        self.add('test_a.py', "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n"
                              "X = ROOT / 'docs' / 'gone.md'\nY = ROOT / 'docs' / 'new-name.md'\n")
        self.add('test_b.py', "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n"
                              "X = ROOT / 'docs' / 'old-name.md'\n")
        self.assertEqual(self.find(['docs/gone.md']), ['test_a.py'])
        self.assertEqual(self.find(['docs/old-name.md', 'docs/new-name.md']), ['test_a.py', 'test_b.py'])

    def test_result_lists_the_documents_read(self):
        f = self.add('test_a.py', "from pathlib import Path\nROOT = Path(__file__).resolve().parents[1]\n"
                                  "X = ROOT / 'docs' / 'guide.md'\n")
        got = mr.reading_tests([f], ['docs/guide.md', 'docs/other.md'], self.top)
        self.assertEqual(got, {f: {'docs/guide.md'}})


if __name__ == '__main__':
    unittest.main()
