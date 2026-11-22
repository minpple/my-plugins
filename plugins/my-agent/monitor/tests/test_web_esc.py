"""esc() of web/index.html: text that goes into an HTML attribute cannot end the attribute."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / 'web' / 'index.html'


class EscTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m = re.search(r'(?m)^const esc = .*$', INDEX.read_text(encoding='utf-8'))
        assert m
        cls.line = m.group(0)

    def test_escapes_double_quote(self):
        self.assertIn(""".replace(/"/g,'&quot;')""", self.line)

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_quoted_command_stays_inside_the_attribute(self):
        # a G2 popup title is the command itself, e.g. grep "^FAIL" (the Parallel timeline lost every agent row)
        src = self.line + """
console.log(JSON.stringify([esc('grep "^FAIL" a&b <x>'), esc(null), esc(0)]));"""
        r = subprocess.run(['node', '-e', src], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), ['grep &quot;^FAIL&quot; a&amp;b &lt;x&gt;', '\u2013', '0'])


if __name__ == '__main__':
    unittest.main()
