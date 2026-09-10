#!/usr/bin/env python3
"""Cloud task: decrypt previous snapshot, collect both accounts, publish only ciphertext."""
import os,sys,json,pathlib,shutil,contextlib,io
BASE=pathlib.Path(__file__).resolve().parent
ROOT=BASE.parent
os.environ["PROMENADA_SITE_DIR"]=str(ROOT)
sys.path.insert(0,str(BASE))
import collector,publisher
WORK=pathlib.Path(os.environ.get("RUNNER_TEMP",str(ROOT.parent.parent/"work")))/"promenada-private"
WORK.mkdir(parents=True,exist_ok=True,mode=0o700)
collector.BASE=publisher.BASE=WORK
def main():
    password=collector.secret("site-password")
    envelope=json.loads((ROOT/"report.enc.json").read_text())
    previous=publisher.decrypt(envelope,password)
    old_digest=previous.pop("digest",{"actions":[],"observations":[]})
    # Observations are regenerated from attendance and must not accumulate.
    old_digest["observations"]=[]
    (WORK/"snapshot.json").write_text(json.dumps(previous,ensure_ascii=False))
    (WORK/"digest.json").write_text(json.dumps(old_digest,ensure_ascii=False))
    failed=False
    with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
        try:
            if "--dry-run" not in sys.argv:collector.main()
        except SystemExit:failed=True
        publisher.build()
    state=json.loads((WORK/"snapshot.json").read_text())
    failed=failed or any(a.get("status")!="ok" for a in state["accounts"].values())
    from stage_site import stage
    stage(ROOT)
    with open(os.environ.get("GITHUB_OUTPUT",str(BASE/"out.txt")),"a") as f:f.write("healthy="+("false" if failed else "true")+"\n")
    for p in ["snapshot.json","digest.json","published-state.json","snapshot.tmp","report.enc.tmp"]:
        (WORK/p).unlink(missing_ok=True)
    print("Encrypted report prepared. "+("Some accounts require attention; last good data preserved." if failed else "All accounts refreshed."))
if __name__=="__main__":
    try:main()
    except Exception:
        print("Report update failed before publication. Existing report was preserved.",file=sys.stderr)
        sys.exit(1)
