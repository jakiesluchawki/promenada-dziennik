#!/usr/bin/env python3
"""Print bounded synthetic-test failure summaries, never raw crash memory or environment."""
import json
import os
from pathlib import Path
import subprocess

result = Path(os.environ['RUNNER_TEMP']) / 'mahbrus-runtime-results.xcresult'
if result.exists():
    command = ['xcrun', 'xcresulttool', 'get', 'test-results', 'summary', '--path', str(result), '--compact']
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        completed = None
        print('xcresult summary timed out')
    if completed is not None and completed.returncode == 0:
        try:
            summary = json.loads(completed.stdout)
            print(json.dumps({key: summary[key] for key in ('title', 'result', 'passedTests', 'failedTests', 'skippedTests', 'testFailures') if key in summary})[:12000])
        except (ValueError, TypeError):
            print('Synthetic test result summary was not JSON')
    elif completed is not None:
        print('xcresult summary unavailable; exit code', completed.returncode)

for path in sorted((Path.home() / 'Library/Logs/DiagnosticReports').glob('Mahbrus*.ips'))[-4:]:
    try:
        with path.open('rb') as stream:
            data = stream.read(2_000_001)
        if len(data) > 2_000_000:
            print('Synthetic crash summary exceeds diagnostic input cap'); continue
        raw = data.decode('utf-8')
        try:
            report = json.loads(raw)
        except ValueError:
            report = json.loads(raw.split('\n', 1)[1])
        index = report.get('faultingThread')
        threads = report.get('threads', [])
        frames = threads[index].get('frames', []) if isinstance(index, int) and 0 <= index < len(threads) else []
        summary = {key: report[key] for key in ('exception', 'termination', 'faultingThread') if key in report}
        summary['frames'] = [{key: frame[key] for key in ('symbol', 'imageIndex', 'imageOffset') if key in frame} for frame in frames[:15]]
        print('Synthetic app crash summary:', json.dumps(summary)[:12000])
    except (OSError, ValueError, TypeError, IndexError):
        print('Synthetic app crash summary unavailable')
