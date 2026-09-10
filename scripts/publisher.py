#!/usr/bin/env python3
"""Build and publish only the encrypted family report. Credentials stay in Keychain."""
import sys,os,json,pathlib,hashlib,base64,secrets,subprocess,datetime,copy
BASE=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(BASE))
from collector import secret
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
SITE=pathlib.Path(os.environ.get("PROMENADA_SITE_DIR",str(BASE.parents[1]/"outputs"/"promenada")))
AAD=b"promenada-report-v1"
ITERATIONS=600000
os.umask(0o077)
def canonical(d):return json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
def key_for(password,salt):
    return PBKDF2HMAC(algorithm=hashes.SHA256(),length=32,salt=salt,iterations=ITERATIONS).derive(password.encode())
def encrypt(d,password):
    salt=secrets.token_bytes(16);iv=secrets.token_bytes(12)
    enc=AESGCM(key_for(password,salt)).encrypt(iv,canonical(d),AAD)
    b=lambda x:base64.b64encode(x).decode()
    return {"v":1,"iterations":ITERATIONS,"salt":b(salt),"iv":b(iv),"ciphertext":b(enc)}
def decrypt(e,password):
    b=lambda x:base64.b64decode(x)
    return json.loads(AESGCM(key_for(password,b(e["salt"]))).decrypt(b(e["iv"]),b(e["ciphertext"]),AAD))
def load_report():
    d=json.loads((BASE/"snapshot.json").read_text())
    digest=json.loads((BASE/"digest.json").read_text()) if (BASE/"digest.json").exists() else {"actions":[],"observations":[]}
    ids={m["id"] for a in d["accounts"].values() for k in ["messages","announcements"] for m in a.get(k,[])}
    for a in digest.get("actions",[]):
        if a.get("source_id") and a["source_id"] not in ids:raise RuntimeError("Digest references an unknown source: "+a["source_id"])
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
    allowed={".git",".gitignore",".nojekyll","index.html","styles.css","app.js","favicon.svg","report.enc.json","ARTWORK.md","README.md","assets","fonts","scripts",".github","requirements.txt","_site","kompakt","ios","students","server","PRODUCT.md","DESIGN.md","tests"}
    for p in SITE.iterdir():
        if p.name not in allowed:raise RuntimeError("Unreviewed file in publishing folder: "+p.name)
    for p in SITE.rglob("*"):
        if p.is_file() and not any(part in p.parts for part in [".git","__pycache__","node_modules",".netlify","_site","build"]) and p.suffix not in [".png",".jpg",".webp",".woff2"]:
            txt=p.read_text(errors="ignore")
            if any(n and n in txt for n in needles):raise RuntimeError("Plaintext private data found in "+p.name)
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
def build(publish=False):
    report=load_report();password=secret("site-password");envelope=encrypt(report,password)
    assert decrypt(envelope,password)==report
    path=SITE/"report.enc.json";tmp=SITE/"report.enc.tmp";tmp.write_text(json.dumps(envelope,separators=(",",":")));tmp.replace(path)
    audit()
    fp=fingerprint(report);state_path=BASE/"published-state.json";old=json.loads(state_path.read_text()) if state_path.exists() else {}
    state={"fingerprint":fp,"collected_at":report["collected_at"],"meaningful_change":old.get("fingerprint")!=fp}
    state_path.write_text(json.dumps(state,indent=2)) if not publish else None
    if publish:
        run_git("add","report.enc.json")
        run_git("commit","-m","Update encrypted family report")
        run_git("push","origin","main")
        state_path.write_text(json.dumps(state,indent=2))
    print(json.dumps({"built":True,"encrypted_bytes":path.stat().st_size,"published":publish,"meaningful_change":state["meaningful_change"],"accounts":{k:a.get("status") for k,a in report["accounts"].items()}}))
if __name__=="__main__":
    if "--verify" in sys.argv:verify()
    elif "--audit" in sys.argv:audit();print("Public folder audit passed")
    else:build("--publish" in sys.argv)
