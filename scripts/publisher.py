#!/usr/bin/env python3
"""Build and publish only the encrypted family report. Credentials stay in Keychain."""
import sys,os,json,pathlib,hashlib,base64,secrets,subprocess,datetime,copy,tempfile,re
BASE=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(BASE))
from collector import secret
from report_errors import ReportError
import report_attachments as attachments
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
SITE=pathlib.Path(os.environ.get("PROMENADA_SITE_DIR",str(BASE.parents[1]/"outputs"/"promenada")))
AAD=b"promenada-report-v1"
ITERATIONS=600000
# Existing iOS clients reject larger encrypted envelopes.
MAX_REPORT_BYTES=25_000_000
os.umask(0o077)
def canonical(d):return json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
def unique_attachments(attachments):
    """Remove only byte-for-byte equivalent records within one message.

    Keep different names, metadata and failures; never coalesce messages/accounts
    or replace inline data with references unsupported by existing clients.
    """
    seen=set();result=[]
    for attachment in attachments:
        if not attachment.get("base64") or attachment.get("error"):
            result.append(attachment);continue
        encoded=canonical(attachment)
        if encoded not in seen:
            seen.add(encoded);result.append(attachment)
    return result

def report_size_metrics(report, encrypted_bytes):
    """Content-free totals only: no account keys, filenames, URLs or text."""
    attachment_bytes=sum(len(canonical(f)) for a in report["accounts"].values()
                         for kind in ("messages","announcements")
                         for m in a.get(kind,[]) for f in m.get("attachments",[]))
    return {"encrypted_bytes":encrypted_bytes,
            "plaintext_bytes":len(canonical(report)),
            "attachment_bytes":attachment_bytes}

def key_for(password,salt):
    return PBKDF2HMAC(algorithm=hashes.SHA256(),length=32,salt=salt,iterations=ITERATIONS).derive(password.encode())
def encrypt(d,password):
    salt=secrets.token_bytes(16);iv=secrets.token_bytes(12)
    enc=AESGCM(key_for(password,salt)).encrypt(iv,canonical(d),AAD)
    b=lambda x:base64.b64encode(x).decode()
    return {"v":1,"iterations":ITERATIONS,"salt":b(salt),"iv":b(iv),"ciphertext":b(enc)}
def decrypt(e,password):
    if not isinstance(e,dict) or type(e.get("v")) is not int or e["v"]!=1 or type(e.get("iterations")) is not int or e["iterations"]!=ITERATIONS:
        raise ValueError("Invalid encrypted report envelope")
    salt=attachments.decode64(e.get("salt"),16);iv=attachments.decode64(e.get("iv"),12)
    ciphertext=attachments.decode64(e.get("ciphertext"))
    if len(ciphertext)<16:raise ValueError("Invalid encrypted report envelope")
    return json.loads(AESGCM(key_for(password,salt)).decrypt(iv,ciphertext,AAD))

def report_paths(root, audience="parent", principal="parent"):
    root=pathlib.Path(root)
    if audience=="parent" and principal=="parent":
        return root/"report.enc.json",root/"report.v2.enc.json"
    if audience=="student" and isinstance(principal,str) and attachments.HEX.fullmatch(principal):
        return root/"students"/(principal+".enc.json"),root/"students"/(principal+".v2.enc.json")
    raise ReportError("attachment_scope")

def current_report_path(root, audience="parent", principal="parent"):
    legacy,manifest=report_paths(root,audience,principal)
    # A corrupt, unreadable or symlinked v2 is never an invitation to downgrade.
    return manifest if manifest.exists() or manifest.is_symlink() else legacy

def load_current_report(root,password,audience="parent",principal="parent",account_key=None,hydrate=False):
    path=current_report_path(root,audience,principal)
    if path.is_symlink() or path.parent.is_symlink():raise ReportError("unreviewed_public_file")
    if not path.is_file():raise ReportError("attachment_unavailable")
    with path.open("rb") as stream:payload=stream.read(MAX_REPORT_BYTES+1)
    if len(payload)>MAX_REPORT_BYTES:raise ReportError("report_too_large",{"encrypted_bytes":len(payload)})
    report=decrypt(json.loads(payload),password)
    attachments.validate_scope(report,audience,principal,account_key)
    if path.name.endswith(".v2.enc.json") and report.get("schema")!=2:
        raise ReportError("attachment_scope")
    return attachments.hydrate(report,root) if hydrate else report

def encrypted_payload_size(report):
    # Exact serialized envelope length without constructing a potentially huge
    # legacy ciphertext. Salt, IV and tag lengths are fixed by the v1 protocol.
    overhead=len(json.dumps({"v":1,"iterations":ITERATIONS,"salt":"x"*24,"iv":"x"*16,"ciphertext":""},separators=(",",":")))
    return overhead+4*((len(canonical(report))+16+2)//3)

def prepare_reports(report,password,root,on_phase=lambda phase:None):
    on_phase("externalize_attachments")
    manifest=attachments.externalize(report,root)
    legacy=attachments.legacy_inline(manifest,root)
    on_phase("encrypt_report")
    envelope=encrypt(manifest,password)
    on_phase("verify_encryption")
    assert decrypt(envelope,password)==manifest
    payload=json.dumps(envelope,separators=(",",":")).encode("utf-8")
    on_phase("write_ciphertext")
    if len(payload)>MAX_REPORT_BYTES:
        raise ReportError("report_too_large",report_size_metrics(manifest,len(payload)))
    inline_size=encrypted_payload_size(legacy)
    inline_payload=None
    if inline_size<=MAX_REPORT_BYTES:
        inline_envelope=encrypt(legacy,password)
        assert decrypt(inline_envelope,password)==legacy
        inline_payload=json.dumps(inline_envelope,separators=(",",":")).encode("utf-8")
        if len(inline_payload)>MAX_REPORT_BYTES:
            raise ReportError("report_too_large",report_size_metrics(legacy,len(inline_payload)))
    return manifest,payload,inline_payload,inline_size

def write_reports(report,password,root,on_phase=lambda phase:None,before_write=lambda:None):
    manifest,payload,inline_payload,inline_size=prepare_reports(report,password,root,on_phase)
    audience,principal=attachments.validate_scope(manifest)
    legacy_path,manifest_path=report_paths(root,audience,principal)
    before_write()
    manifest_path.parent.mkdir(exist_ok=True)
    if manifest_path.parent.is_symlink() or manifest_path.is_symlink() or legacy_path.is_symlink():
        raise ReportError("unreviewed_public_file")
    pending=[]
    try:
        # Write and fsync every replacement before switching authoritative v2.
        for target,data in [(legacy_path,inline_payload),(manifest_path,payload)]:
            if data is None:continue
            with tempfile.NamedTemporaryFile(dir=target.parent,prefix=".report-",delete=False) as stream:
                temporary=pathlib.Path(stream.name);pending.append((temporary,target))
                stream.write(data);stream.flush();os.fsync(stream.fileno())
        for temporary,target in pending:temporary.replace(target)
    finally:
        for temporary,_ in pending:temporary.unlink(missing_ok=True)
    return {"path":manifest_path,"legacy_updated":inline_payload is not None,
            "legacy_encrypted_bytes":inline_size,"encrypted_bytes":len(payload)}

def load_report():
    d=json.loads((BASE/"snapshot.json").read_text())
    digest=json.loads((BASE/"digest.json").read_text()) if (BASE/"digest.json").exists() else {"actions":[],"observations":[]}
    ids={m["id"] for a in d["accounts"].values() for k in ["messages","announcements"] for m in a.get(k,[])}
    for a in digest.get("actions",[]):
        if a.get("source_id") and a["source_id"] not in ids:raise ReportError("digest_unknown_source")
    d["digest"]=digest
    if os.environ.get("PARENT_REFRESH_CONFIG"):
        d["refresh"]=json.loads(os.environ["PARENT_REFRESH_CONFIG"])
    names={k:v.get("display_name",k.capitalize()) for k,v in json.loads(secret("accounts")).items()}
    for key,a in d["accounts"].items():
        a["name"]=names[key]
        sec=a.get("sections",{})
        # Raw fallback text preserves access if a structured parser misses a new layout.
        # Large layout tables duplicate that content, so they are not sent to the site.
        for section_name,s in sec.items():
            s.pop("tables",None);s.pop("tips",None);s.pop("revision",None)
            s["revision"]=hashlib.sha256(canonical([key,section_name,s])).hexdigest()[:32]
        for kind in ["messages","announcements"]:
            for m in a.get(kind,[]):
                if "attachments" in m:
                    m["attachments"]=unique_attachments(m["attachments"])
                m["revision"]=hashlib.sha256(canonical([m["id"],m["title"],m["text"],[(f["name"],f.get("size",0)) for f in m.get("attachments",[])]] )).hexdigest()[:32]
    for a in digest.get("actions",[]):
        a["id"]=hashlib.sha256(canonical([a["child"],a.get("source_id",a.get("section","")),a["title"]])).hexdigest()[:24]
        a["revision"]=hashlib.sha256(canonical([a["id"],a["text"],a.get("date")])).hexdigest()[:32]
    observations=list(digest.get("observations",[]))
    for key,a in d["accounts"].items():
        att=a.get("sections",{}).get("attendance",{})
        count=att.get("counts",{}).get("nb",0)
        entries=att.get("entries",[])
        if count:
            dates=sorted(e["date"] for e in entries if e["code"]=="nb")
            observations.append({"child":key,"kind":"Frekwencja","title":str(count)+" wpisów nieobecności","text":"Librus oznacza kodem „nb” "+str(count)+" godzin lekcyjnych, od "+dates[0]+" do "+dates[-1]+". To stan wpisów szkoły; rozwiń frekwencję, aby sprawdzić lekcje i autorów.","section":"attendance"})
        trips=sorted(set(e["date"] for e in entries if "Czy wycieczka: Tak" in e.get("details","")))
        for date in trips:
            observations.append({"child":key,"date":date,"kind":"Wycieczka w frekwencji","title":"Zwolnienia oznaczone jako wycieczka","text":"Wpisy zwolnień w Librusie mają oznaczenie „Czy wycieczka: Tak”. Odwołane lekcje tego dnia nie potwierdzają pobytu w domu. Godzin samej wycieczki nie ma w odczytanym planie.","section":"attendance"})
    d["digest"]["observations"]=observations
    return d
def fingerprint(d):
    out=copy.deepcopy(d);out.pop("collected_at",None)
    out.get("digest",{}).pop("updated_at",None)
    for a in out["accounts"].values():
        a.pop("checked_at",None);a.pop("new_ids",None)
    return hashlib.sha256(canonical(out)).hexdigest()
def audit():
    credentials=secret("accounts")
    credential_values=[x for a in json.loads(credentials).values() for k,x in a.items() if k in ["login","password"]]
    needles=credential_values+[secret("site-password")]+[a["expected"] for a in json.loads(credentials).values()]
    # Also scan enrolled student credentials when available locally or in Actions.
    try:
        student_accounts=json.loads(secret("student-accounts"))
        needles += [value for account in student_accounts.values() for field,value in account.items() if field in ("login","password","expected")]
    except (RuntimeError, OSError): pass
    allowed={".git",".gitignore",".nojekyll","index.html","styles.css","app.js","favicon.svg","report.enc.json","report.v2.enc.json","attachments","ARTWORK.md","README.md","assets","fonts","scripts",".github","requirements.txt","_site","kompakt","ios","students","server","PRODUCT.md","DESIGN.md","tests"}
    for p in SITE.iterdir():
        if p.name not in allowed:raise ReportError("unreviewed_public_file")
    from stage_site import encrypted_public_paths
    encrypted_public_paths(SITE)
    blob_files=set(attachments.public_blob_files(SITE))
    for p in SITE.rglob("*"):
        if p in blob_files:continue
        if p.is_file() and not any(part in p.parts for part in [".git","__pycache__","node_modules",".netlify","_site","build"]) and p.suffix not in [".png",".jpg",".webp",".woff2"]:
            txt=p.read_text(errors="ignore")
            if any(n and n in txt for n in needles):raise ReportError("plaintext_public_file")
    return True
def verify():
    password=secret("site-password");report=load_report();envelope=encrypt(report,password)
    assert decrypt(envelope,password)==report
    from cryptography.exceptions import InvalidTag
    try:decrypt(envelope,password+"wrong")
    except InvalidTag:pass
    else:raise AssertionError("Wrong password accepted")
    altered=dict(envelope);raw=bytearray(base64.b64decode(altered["ciphertext"]));raw[25]^=1;altered["ciphertext"]=base64.b64encode(raw).decode()
    try:decrypt(altered,password)
    except InvalidTag:pass
    else:raise AssertionError("Modified ciphertext accepted")
    for key,a in report["accounts"].items():
        assert a["status"]=="ok"
        assert len(a["sections"]["timetable"]["days"])==5
        assert set(["messages","announcements","sections"])<=a.keys()
        for s in ["grades","attendance","notes","dates","homework","achievements"]:assert s in a["sections"]
        att=a["sections"]["attendance"];assert sum(att["counts"].values())==len([e for e in att["entries"] if e["code"] in att["counts"]])
    print(json.dumps({"encryption_roundtrip":True,"wrong_password_rejected":True,"tamper_rejected":True,"accounts_verified":len(report["accounts"])}))
def run_git(*args):
    return subprocess.run(["git","-C",str(SITE),*args],check=True,capture_output=True,text=True).stdout.strip()
def build(publish=False, on_phase=lambda phase: None):
    on_phase("load_report")
    report=load_report();password=secret("site-password")
    def check_public_files():
        on_phase("audit_public_files")
        audit()
    result=write_reports(report,password,SITE,on_phase=on_phase,before_write=check_public_files)
    path=result["path"]
    on_phase("prepare_state")
    fp=fingerprint(report);state_path=BASE/"published-state.json";old=json.loads(state_path.read_text()) if state_path.exists() else {}
    state={"fingerprint":fp,"collected_at":report["collected_at"],"meaningful_change":old.get("fingerprint")!=fp}
    state_path.write_text(json.dumps(state,indent=2)) if not publish else None
    if publish:
        from stage_site import encrypted_public_paths
        run_git("add","--",*[str(p.relative_to(SITE)) for p in encrypted_public_paths(SITE)])
        run_git("commit","-m","Update encrypted family report")
        run_git("push","origin","main")
        state_path.write_text(json.dumps(state,indent=2))
    print(json.dumps({"built":True,"encrypted_bytes":path.stat().st_size,"published":publish,"meaningful_change":state["meaningful_change"],"accounts_checked":len(report["accounts"]),"legacy_updated":result["legacy_updated"],"legacy_encrypted_bytes":result["legacy_encrypted_bytes"]}))
if __name__=="__main__":
    from report_errors import Diagnostics
    diagnostics=Diagnostics()
    try:
        if "--verify" in sys.argv:verify()
        elif "--audit" in sys.argv:audit();print("Public folder audit passed")
        else:build("--publish" in sys.argv,on_phase=diagnostics.set_phase)
    except Exception as error:
        print("Report preparation failed. "+diagnostics.failure(error),file=sys.stderr)
        sys.exit(1)
