"""Run actual JavaScript reader behavior against in-memory synthetic responses only."""
import pathlib
import shutil
import subprocess
import unittest


class WebReader(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for browser-reader checks')
    def test_scoped_attachment_protocol_and_interrupted_ui(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', '--test', 'tests/test_web_attachments.cjs'],
                                cwd=root, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
