"""Real main runs must count even when GitHub's branch query would hide them."""
import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import dispatch_guard


class WorkflowHistoryGuard(unittest.TestCase):
    def test_cooldown_uses_locally_filtered_history_for_both_profiles(self):
        for workflow in ['update.yml', 'update-student.yml']:
            for include_main in [True, False]:
                with self.subTest(workflow=workflow, include_main=include_main), tempfile.TemporaryDirectory() as directory:
                    output = pathlib.Path(directory) / 'output'
                    base = {'created_at': datetime.now(timezone.utc).isoformat(), 'head_branch': 'main', 'path': '.github/workflows/'+workflow}
                    runs = [dict(base, id=98, head_branch='feature'), dict(base, id=97, path='.github/workflows/unrelated.yml')]
                    if include_main: runs.append(dict(base, id=99))
                    def fetch(request, timeout):
                        # Regression fixture: the remote branch query returns no matches.
                        data = [] if 'branch=' in request.full_url else runs
                        return io.BytesIO(json.dumps({'workflow_runs': data}).encode())
                    with patch.dict(os.environ, {'MAHBRUS_WORKFLOW': workflow, 'GH_TOKEN': 'synthetic-only', 'GITHUB_RUN_ID': '100', 'GITHUB_OUTPUT': str(output)}), \
                         patch.object(dispatch_guard.urllib.request, 'urlopen', side_effect=fetch), \
                         contextlib.redirect_stdout(io.StringIO()):
                        dispatch_guard.main()
                    self.assertEqual(output.read_text(), 'allowed='+str(not include_main).lower()+'\n')


if __name__ == '__main__':
    unittest.main()
