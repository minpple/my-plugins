import unittest
from pathlib import Path

GUIDE = Path(__file__).resolve().parents[1] / 'docs' / 'guide.md'


class GuideTest(unittest.TestCase):
    def test_guide_names_add(self):
        self.assertIn('add', GUIDE.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
