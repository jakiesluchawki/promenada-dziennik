#!/usr/bin/env python3
"""Stage only reviewed public assets and validated immutable ciphertext paths."""
from pathlib import Path
import hashlib, json, re, shutil, subprocess, sys
import publisher
from report_errors import ReportError
from report_attachments import decode64, public_blob_files

PUBLIC_FILES = ('index.html', 'styles.css', 'app.js', 'favicon.svg', '.nojekyll')
PUBLIC_DIRS = ('assets', 'fonts', 'kompakt')
STUDENT_NAME = re.compile(r'[a-f0-9]{64}(?:\.v2)?\.enc\.json')


def validate_manifest_file(source):
    if source.is_symlink() or not source.is_file():
        raise ReportError('unreviewed_public_file')
    with source.open('rb') as stream: data = stream.read(publisher.MAX_REPORT_BYTES + 1)
    if len(data) > publisher.MAX_REPORT_BYTES:
        raise ReportError('report_too_large', {'encrypted_bytes': len(data)})
    envelope = json.loads(data)
    if (not isinstance(envelope, dict) or type(envelope.get('v')) is not int or envelope['v'] != 1
            or type(envelope.get('iterations')) is not int or envelope['iterations'] != publisher.ITERATIONS
            or set(envelope) != {'v', 'iterations', 'salt', 'iv', 'ciphertext'}):
        raise ReportError('unreviewed_public_file')
    decode64(envelope['salt'], 16)
    decode64(envelope['iv'], 12)
    if len(decode64(envelope['ciphertext'])) < 16:
        raise ReportError('unreviewed_public_file')


def encrypted_public_paths(root):
    root = Path(root)
    files = []
    for name in ('report.enc.json', 'report.v2.enc.json'):
        source = root / name
        if source.exists() or source.is_symlink():
            validate_manifest_file(source)
            files.append(source)
    students = root / 'students'
    if students.is_symlink() or (students.exists() and not students.is_dir()):
        raise ReportError('unreviewed_public_file')
    if students.is_dir():
        for source in sorted(students.iterdir()):
            if not STUDENT_NAME.fullmatch(source.name):
                raise ReportError('unreviewed_public_file')
            validate_manifest_file(source)
            files.append(source)
    return files + public_blob_files(root)


def stage(root):
    root = Path(root)
    files = encrypted_public_paths(root)
    if not any(path.name in ('report.enc.json', 'report.v2.enc.json') for path in files):
        raise ReportError('unreviewed_public_file')
    out = root / '_site'
    if out.exists(): shutil.rmtree(out)
    out.mkdir()
    for name in PUBLIC_FILES: shutil.copy2(root / name, out / name)
    for name in PUBLIC_DIRS: shutil.copytree(root / name, out / name)
    for source in files:
        target = out / source.relative_to(root)
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(source, target)
    for folder in (out, out / 'kompakt'):
        page = folder / 'index.html'; html = page.read_text()
        for name in ('styles.css', 'app.js'):
            if not (folder / name).is_file(): continue
            version = hashlib.sha256((folder / name).read_bytes()).hexdigest()[:12]
            html = re.sub(r'(href|src)="\./' + re.escape(name) + r'(?:\?[^"]*)?"',
                          lambda m: m.group(1) + '="./' + name + '?v=' + version + '"', html)
        page.write_text(html)
    return out


def stage_git(root):
    root = Path(root)
    # Never glob or add a directory: every path passed to git has been checked.
    paths = [str(path.relative_to(root)) for path in encrypted_public_paths(root)]
    if paths:
        subprocess.run(['git', '-C', str(root), 'add', '--', *paths], check=True,
                       capture_output=True, text=True)


if __name__ == '__main__':
    try:
        root = Path(__file__).resolve().parent.parent
        if '--git-add' in sys.argv: stage_git(root)
        else: stage(root)
        print('Validated encrypted reports and public assets prepared.')
    except Exception:
        print('Public staging failed validation; no private details logged.', file=sys.stderr)
        sys.exit(1)
