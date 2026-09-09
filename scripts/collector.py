#!/usr/bin/env python3
import sys,os,json,pathlib,ctypes,time,random,re,hashlib
from urllib.parse import urlparse,urljoin
BASE=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(BASE/"vendor"))
import requests
from bs4 import BeautifulSoup
os.umask(0o077)
SERVICE=b"pl.mahboob.promenada.librus"
def secret(account):
    env_name={"accounts":"LIBRUS_ACCOUNTS","site-password":"SITE_PASSWORD"}.get(account)
    if env_name and os.environ.get(env_name): return os.environ[env_name]
    lib=ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
    f=lib.SecKeychainFindGenericPassword
    f.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_char_p,ctypes.c_uint32,ctypes.c_char_p,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_void_p),ctypes.c_void_p]
    f.restype=ctypes.c_int32
    length=ctypes.c_uint32(); data=ctypes.c_void_p(); acc=account.encode()
    status=f(None,len(SERVICE),SERVICE,len(acc),acc,ctypes.byref(length),ctypes.byref(data),None)
    if status: raise RuntimeError("Keychain access error "+str(status))
    out=ctypes.string_at(data,length.value)
    lib.SecKeychainItemFreeContent(None,data)
    return out.decode()
def login(key):
    info=json.loads(secret("accounts"))[key]
    s=requests.Session()
    s.headers["User-Agent"]="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    r=s.get("https://synergia.librus.pl/loguj/portalRodzina",timeout=30)
    r.raise_for_status()
    if urlparse(r.url).hostname!="api.librus.pl": raise RuntimeError("Unexpected login destination")
    c=s.post("https://api.librus.pl/OAuth/Captcha",data={"username":info["login"],"is_needed":1},headers={"X-Requested-With":"XMLHttpRequest","Referer":r.url},timeout=30)
    c.raise_for_status()
    if c.json().get("is_needed"): raise RuntimeError("Librus requires CAPTCHA; user action needed")
    encode=lambda st: "".join(chr(ord(x)+20) for x in st)
    baner=encode(str(random.random()))+"_"+encode(str(int(time.time()*1000)))
    a=s.post(r.url,data={"action":"login","login":info["login"],"pass":info["password"]},headers={"x-baner":baner,"X-Requested-With":"XMLHttpRequest","Referer":r.url},timeout=30)
    try: result=a.json()
    except ValueError: raise RuntimeError("Login returned non-JSON status "+str(a.status_code))
    if result.get("status")!="ok":
        raise RuntimeError("Login requires attention: "+str(result.get("status"))+" "+str([e.get("message","") for e in result.get("errors",[])]))
    target=urljoin(r.url,result.get("goTo",""))
    if urlparse(target).hostname not in ["synergia.librus.pl","api.librus.pl"]: raise RuntimeError("Unexpected login redirect")
    s.get(target,timeout=30).raise_for_status()
    page=s.get("https://synergia.librus.pl/wiadomosci",timeout=30)
    page.raise_for_status()
    doc=BeautifulSoup(page.text,"html.parser")
    identity=doc.select_one("#user-section") or doc.select_one(".user-section")
    text=doc.get_text(" ",strip=True)
    if info["expected"] not in text or "wyloguj" not in page.text.lower(): raise RuntimeError("Account identity not confirmed")
    return s,doc,page.text

def text_clean(el):
    if not el: return ""
    for tag in el.select("script,style,noscript"): tag.decompose()
    text=el.get_text("\n",strip=True)
    return re.sub(r"\n{3,}","\n\n",text).strip()
def checked_get(s,url):
    if urlparse(url).hostname!="synergia.librus.pl": raise RuntimeError("Unsupported content destination")
    r=s.get(url,timeout=30);r.raise_for_status()
    if urlparse(r.url).hostname!="synergia.librus.pl" or "/loguj" in r.url: raise RuntimeError("Session expired")
    return BeautifulSoup(r.text,"html.parser")

def tooltip(value):
    return BeautifulSoup(value or "", "html.parser").get_text("\n",strip=True)
def cell_info(cell):
    return {"text":cell.get_text(" ",strip=True),"details":list(dict.fromkeys(tooltip(e.get("title") or e.get("alt")) for e in cell.select("[title],[alt]") if e.get("title") or e.get("alt"))),"colspan":int(cell.get("colspan",1)),"rowspan":int(cell.get("rowspan",1))}
def parse_section(name,d,section):
    body=d.select_one("#body") or d
    tables=[]
    for table in body.select("table"):
        if table.find_parent("table"):continue
        rows=[]
        for row in table.find_all("tr"):
            if row.find_parent("table")!=table:continue
            cells=row.find_all(["td","th"],recursive=False)
            if cells:rows.append([cell_info(c) for c in cells])
        if rows:tables.append(rows)
    section["tables"]=tables
    section["tips"]=list(dict.fromkeys(tooltip(e["title"]) for e in body.select("[title]") if e["title"]))
    if name=="grades":
        subjects=[]
        for row in body.select("tr"):
            cells=row.find_all(["td","th"],recursive=False)
            if len(cells)==10 and row.select_one('img[id^="przedmioty_"]'):
                grades=[]
                for pos,term in [(2,1),(5,2)]:
                    for a in cells[pos].select("a.ocena"):
                        grades.append({"value":a.get_text(" ",strip=True),"term":term,"details":tooltip(a.get("title"))})
                subjects.append({"subject":cells[1].get_text(" ",strip=True),"grades":grades,"term1":cells[2].get_text(" ",strip=True),"term2":cells[5].get_text(" ",strip=True),"final1":cells[4].get_text(" ",strip=True),"final2":cells[7].get_text(" ",strip=True),"year":cells[9].get_text(" ",strip=True)})
        section["subjects"]=subjects
        descriptive=[]
        for h in body.find_all(["h2","h3"]):
            if "opisowe" in h.get_text().lower():
                table=h.find_next("table")
                if table:
                    for row in table.select("tr"):
                        cells=row.find_all(["td","th"],recursive=False)
                        if len(cells)>=2 and "Obszar oceniania" not in row.get_text():
                            descriptive.append({"area":cells[1].get_text(" ",strip=True),"text":" ".join(c.get_text(" ",strip=True) for c in cells[2:]),"details":[tooltip(x["title"]) for x in row.select("[title]")]})
        section["descriptive"]=[x for x in descriptive if x["area"].startswith("Edukacja ")]
    if name=="attendance":
        entries=[]
        for row in body.select("tr"):
            cells=row.find_all(["td","th"],recursive=False)
            if not cells:continue
            date=cells[0].get_text(" ",strip=True)
            if not re.match(r"\d{4}-\d{2}-\d{2}",date):continue
            for a in row.select("a.ocena"):
                entries.append({"date":date[:10],"code":a.get_text(" ",strip=True),"details":tooltip(a.get("title"))})
        section["entries"]=entries
        section["counts"]={code:sum(1 for x in entries if x["code"]==code) for code in ["nb","u","sp","zw"]}
    if name=="dates":
        selected=[o.get("value") for o in d.select("select option[selected]")]
        year=next((x for x in selected if x and re.fullmatch("20\\d{2}",x)),str(__import__("datetime").date.today().year))
        month=next((x for x in selected if x and x.isdigit() and 1<=int(x)<=12),str(__import__("datetime").date.today().month))
        events=[]
        for day in d.select(".kalendarz-dzien"):
            number=day.select_one(".kalendarz-numer-dnia")
            if not number or not number.get_text(strip=True).isdigit():continue
            daynum=int(number.get_text(strip=True))
            for cell in day.select("td[title],td[onclick]"):
                text=cell.get_text(" ",strip=True)
                if text:events.append({"date":f"{int(year):04d}-{int(month):02d}-{daynum:02d}","text":text,"details":tooltip(cell.get("title"))})
        section["events"]=events
    if name in ["notes","achievements"]:
        section["empty"]=bool(re.search(r"Brak (uwag|szczególnych osiągnięć)",section["text"],re.I))


def download_attachment(s,url,name):
    import base64
    r=s.get(url,timeout=30);r.raise_for_status()
    if "text/html" in r.headers.get("Content-Type",""):
        if urlparse(r.url).hostname!="sandbox.librus.pl":raise RuntimeError("Unexpected attachment page")
        key=re.search(r'var singleUseKey = "([^"]+)"',r.text)
        if not key:raise RuntimeError("Attachment download key missing")
        value=key.group(1)
        for _ in range(6):
            check=s.post("https://sandbox.librus.pl/index.php?action=CSCheckKey",data={"singleUseKey":value},timeout=30)
            check.raise_for_status()
            state=check.json().get("status")
            if state=="ready":break
            if state!="not_downloaded_yet":raise RuntimeError("Attachment unavailable")
            time.sleep(2)
        else:raise RuntimeError("Attachment preparation timed out")
        r=s.get("https://sandbox.librus.pl/index.php",params={"action":"CSDownload","singleUseKey":value},timeout=45)
        r.raise_for_status()
    if "text/html" in r.headers.get("Content-Type",""):raise RuntimeError("Attachment is not a downloadable file")
    if len(r.content)>8_000_000:raise RuntimeError("Attachment exceeds 8 MB")
    return {"name":name,"mime":r.headers.get("Content-Type","application/octet-stream").split(";")[0],"base64":base64.b64encode(r.content).decode(),"size":len(r.content)}

def collect_account(key, previous):
    s,doc,_=login(key)
    known={x["id"]:x for x in previous.get("messages",[])}
    messages=[]; seen=set()
    pages=[doc]
    for page in pages:
        for row in page.select("tr"):
            links=row.select('a[href*="/wiadomosci/1/5/"]')
            if not links: continue
            url=urljoin("https://synergia.librus.pl",links[-1]["href"])
            match=re.search(r"/wiadomosci/1/5/(\d+)",url)
            if not match:continue
            mid=key+":message:"+match[1]
            if mid in seen: continue
            seen.add(mid)
            if mid in known and known[mid].get("attachment_version")==2 and not any(f.get("error") for f in known[mid].get("attachments",[])): messages.append(known[mid]);continue
            detail=checked_get(s,url)
            content=detail.select_one(".container-message-content")
            if content is None: raise RuntimeError("Message parser did not find content")
            meta={}
            for tr in detail.select("tr"):
                cells=tr.find_all(["td","th"],recursive=False)
                if len(cells)==2:
                    label=cells[0].get_text(" ",strip=True)
                    if label in ["Nadawca","Temat","Wysłano"]: meta[label]=cells[1].get_text(" ",strip=True)
            body=detail.select_one("#body") or detail
            attachments=[]
            for a in body.select("a[href]"):
                href=urljoin(url,a["href"])
                if urlparse(href).hostname=="synergia.librus.pl" and any(t in href.lower() for t in ("pobierz","download","zalacznik")):
                    attachments.append({"name":a.get_text(" ",strip=True) or "Załącznik","url":href})
            for el in body.select("[onclick]"):
                js=el.get("onclick","").replace("\\/", "/")
                match=re.search(r"(/wiadomosci/pobierz_zalacznik/\d+/\d+)",js)
                if not match:continue
                row=el.find_parent("tr")
                filename=row.find("td").get_text(" ",strip=True) if row else "Załącznik"
                try: attachments.append(download_attachment(s,"https://synergia.librus.pl"+match.group(1),filename))
                except Exception as e: attachments.append({"name":filename,"error":str(e),"url":url})
            messages.append({"attachment_version":2,"id":mid,"child":key,"kind":"message","title":meta.get("Temat",links[-1].get_text(" ",strip=True)),"sender":meta.get("Nadawca",links[0].get_text(" ",strip=True)),"date":meta.get("Wysłano",""),"text":text_clean(content),"url":url,"attachments":attachments})
            time.sleep(.15)
        next_link=page.find("a",string=re.compile(r"^(następna|następne|dalej|next)",re.I))
        if next_link and next_link.get("href"):
            if len(pages)>=20:raise RuntimeError("Mailbox page limit reached")
            pages.append(checked_get(s,urljoin("https://synergia.librus.pl",next_link["href"])))
    for mid,m in known.items():
        if mid not in seen: messages.append(m)
    announcements=[]
    ann=checked_get(s,"https://synergia.librus.pl/ogloszenia")
    for table in ann.select("#body table"):
        txt=text_clean(table)
        if "Data publikacji" not in txt or "Treść" not in txt:continue
        cells=table.find_all("tr")
        title=cells[0].get_text(" ",strip=True) if cells else "Ogłoszenie"
        fields={}
        for row in cells[1:]:
            td=row.find_all(["td","th"],recursive=False)
            if len(td)==2: fields[td[0].get_text(" ",strip=True)]=text_clean(td[1])
        body=fields.get("Treść","")
        identity=key+":announcement:"+hashlib.sha256((title+"|"+fields.get("Data publikacji","")+"|"+body).encode()).hexdigest()[:16]
        announcements.append({"id":identity,"child":key,"kind":"announcement","title":title,"sender":fields.get("Dodał",""),"date":fields.get("Data publikacji",""),"text":body,"url":"https://synergia.librus.pl/ogloszenia","attachments":[]})
    sections={}
    for name,path in [("timetable","/przegladaj_plan_lekcji"),("dates","/terminarz"),("homework","/moje_zadania"),("grades","/przegladaj_oceny/uczen"),("attendance","/przegladaj_nb/uczen"),("notes","/uwagi"),("achievements","/szczegolne_osiagniecia_ucznia")]:
        d=checked_get(s,"https://synergia.librus.pl"+path)
        body=d.select_one("#body") or d
        for tag in body.select(".ad, .banner, iframe"):tag.decompose()
        sections[name]={"text":text_clean(body),"url":"https://synergia.librus.pl"+path}
        parse_section(name,d,sections[name])
        if name=="timetable":
            schedules=[]
            for table in d.select("table"):
                rows=table.find_all("tr")
                if not rows:continue
                headers=rows[0].find_all(["td","th"],recursive=False)
                if not any("Poniedziałek" in h.get_text() for h in headers):continue
                days=[{"label":h.get_text(" ",strip=True),"lessons":[]} for h in headers[2:7]]
                for row in rows[1:]:
                    cells=row.find_all(["td","th"],recursive=False)
                    if len(cells)<7:continue
                    number=cells[0].get_text(" ",strip=True)
                    if not number.isdigit():continue
                    hours=cells[1].get_text(" ",strip=True)
                    for idx,cell in enumerate(cells[2:7]):
                        txt=cell.get_text(" ",strip=True)
                        if txt:
                            tips=[BeautifulSoup(x.get("title") or x.get("onmouseover") or "", "html.parser").get_text(" ",strip=True) for x in cell.select("a[title],a[onmouseover]")]
                            days[idx]["lessons"].append({"number":number,"time":hours,"text":txt,"details":tips})
                schedules=days
                break
            sections[name]["days"]=schedules
    return {"child":key,"status":"ok","checked_at":__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),"messages":messages,"announcements":announcements,"sections":sections}
def main():
    path=BASE/"snapshot.json"
    previous=json.loads(path.read_text()) if path.exists() else {"accounts":{}}
    snapshot={"schema":1,"collected_at":__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),"accounts":{}}
    for key in json.loads(secret("accounts")):
        old=previous.get("accounts",{}).get(key,{})
        try:
            data=collect_account(key,old)
            old_ids={x["id"] for x in old.get("messages",[])+old.get("announcements",[])}
            new_ids=[x["id"] for x in data["messages"]+data["announcements"] if x["id"] not in old_ids]
            data["new_ids"]=new_ids
            snapshot["accounts"][key]=data
            print(json.dumps({"child":key,"status":"ok","messages":len(data["messages"]),"announcements":len(data["announcements"]),"new":len(new_ids),"timetable_days":len(data["sections"]["timetable"]["days"])},ensure_ascii=False))
        except Exception as e:
            data=dict(old);data["status"]="error";data["error"]=str(e);data["child"]=key
            snapshot["accounts"][key]=data
            print(json.dumps({"child":key,"status":"error","error":str(e)},ensure_ascii=False))
    tmp=BASE/"snapshot.tmp"
    tmp.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2));tmp.replace(path)
    if not all(a.get("status")=="ok" for a in snapshot["accounts"].values()):sys.exit(2)
if __name__=="__main__":main()
