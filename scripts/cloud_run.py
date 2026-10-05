#!/usr/bin/env python3
"""Cloud task: decrypt previous snapshot, collect both accounts, publish only ciphertext."""
import os, sys, json, pathlib, contextlib, io, tempfile

BASE = pathlib.Path(__file__).resolve().parent
ROOT = BASE.parent
os.environ["PROMENADA_SITE_DIR"] = str(ROOT)
sys.path.insert(0, str(BASE))
import collector, publisher
from report_errors import Diagnostics
from report_sources import reconcile_sources


def main(on_phase=lambda phase: None):
    on_phase("prepare_workspace")
    # Context-managed, mode-0700 directory is removed on success and failure.
    with tempfile.TemporaryDirectory(prefix="promenada-private-", dir=os.environ.get("RUNNER_TEMP")) as temporary:
        work = pathlib.Path(temporary)
        old_bases = collector.BASE, publisher.BASE
        collector.BASE = publisher.BASE = work
        try:
            on_phase("decrypt_previous")
            password = collector.secret("site-password")
            previous = publisher.load_current_report(ROOT, password, audience="parent", principal="parent")
            on_phase("hydrate_attachments")
            previous = publisher.attachments.hydrate(previous, ROOT)
            on_phase("prepare_snapshot")
            old_digest = previous.pop("digest", {"actions": [], "observations": []})
            # Observations are regenerated from attendance and must not accumulate.
            old_digest["observations"] = []
            (work / "snapshot.json").write_text(json.dumps(previous, ensure_ascii=False))
            (work / "digest.json").write_text(json.dumps(old_digest, ensure_ascii=False))
            failed = False
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                on_phase("collect")
                try:
                    if "--dry-run" not in sys.argv:
                        collector.main()
                except SystemExit:
                    failed = True
                on_phase("reconcile_sources")
                snapshot = json.loads((work / "snapshot.json").read_text())
                snapshot = reconcile_sources(previous, snapshot, old_digest)
                temporary_snapshot = work / "snapshot.tmp"
                temporary_snapshot.write_text(json.dumps(snapshot, ensure_ascii=False))
                temporary_snapshot.replace(work / "snapshot.json")
                publisher.build(on_phase=on_phase)
            on_phase("check_collection")
            state = json.loads((work / "snapshot.json").read_text())
            failed = failed or any(a.get("status") != "ok" for a in state["accounts"].values())
            on_phase("stage_site")
            from stage_site import stage
            stage(ROOT)
            on_phase("write_health")
            with open(os.environ.get("GITHUB_OUTPUT", str(BASE / "out.txt")), "a") as output:
                output.write("healthy=" + ("false" if failed else "true") + "\n")
            on_phase("cleanup")
        finally:
            collector.BASE, publisher.BASE = old_bases
    print("Encrypted report prepared. " + ("Some accounts require attention; last good data preserved." if failed else "All accounts refreshed."))


def run():
    diagnostics = Diagnostics()
    try:
        main(on_phase=diagnostics.set_phase)
    except Exception as error:
        # Only allowlisted labels may enter public Actions logs. Never print the
        # exception, its traceback, paths, source IDs, credentials or report data.
        print("Report update failed before publication. Previously published report was preserved. " + diagnostics.failure(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
