import unittest
from pathlib import Path

README = Path(__file__).resolve().parents[1] / 'README.md'


class ReadmeTest(unittest.TestCase):
    def test_readme_names_the_guide(self):
        self.assertIn('docs/guide.md', README.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
