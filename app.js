"use strict";
let data=null, keyMaterial=null, selected="all", current="overview", query="", activity=Date.now();
const $=id=>document.getElementById(id);
const sections=[
["overview","Przegląd","Szkoła w jednym miejscu.","Najważniejsze sprawy, nadchodzące terminy i pełny obraz szkolnego tygodnia."],
["messages","Wiadomości","Słowo ze szkoły.","Wspólna skrzynka. Pełna treść wiadomości i załączniki, uporządkowane od najnowszych."],
["announcements","Ogłoszenia","Na szkolnej tablicy.","Komunikaty szkół i nauczycieli. Każdy z datą, autorem i wskazaniem dziecka."],
["timetable","Plan lekcji","Rytm tygodnia.","Godziny od pierwszej do ostatniej lekcji. Rozwiń dzień, aby zobaczyć przedmioty, sale i zmiany."],
["dates","Terminy","Warto pamiętać.","Terminarz z Librusa oraz daty odczytane z wiadomości. Źródło jest zawsze pod ręką."],
["grades","Oceny","Małe i duże postępy.","Oceny bieżące i opisowe. Szczegóły wpisów dokładnie tak, jak udostępnia je szkoła."],
["attendance","Frekwencja","Obecność ma znaczenie.","Wpisy o obecności, zwolnieniach i spóźnieniach. Liczymy wpisy, nie domyślamy się przyczyn."],
["notes","Uwagi","Spojrzenie nauczyciela.","Uwagi i spostrzeżenia ze szkoły, zebrane osobno dla każdego dziecka."],
["homework","Zadania","Na spokojne popołudnie.","Zadania z modułu prac domowych i z terminarza. Także lektury i dłuższe przygotowania."],
["achievements","Osiągnięcia","Powody do dumy.","Szczególne osiągnięcia zapisane przez szkołę. Miejsce na to, co warte zapamiętania."]
];
function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n}
function button(label,fn,cls=""){const n=el("button",cls,label);n.type="button";n.addEventListener("click",fn);return n}
function name(key){return data?.accounts[key]?.name||""}
function chosen(){return Object.values(data.accounts).filter(a=>selected==="all"||a.child===selected)}
function datePL(s,options={day:"numeric",month:"long"}){if(!s)return "";const d=new Date(s.length===10?s+"T12:00:00":s.replace(" ","T"));return Number.isNaN(+d)?s:new Intl.DateTimeFormat("pl-PL",{timeZone:"Europe/Warsaw",...options}).format(d)}
function dayISO(){return new Intl.DateTimeFormat("sv-SE",{timeZone:"Europe/Warsaw"}).format(new Date())}
function safeLink(url,label){const a=el("a","source-link",label);try{const u=new URL(url);if(!["https:","http:"].includes(u.protocol))return el("span","muted",label);a.href=u.href;a.target="_blank";a.rel="noopener noreferrer";return a}catch{return el("span","muted",label)}}
function pill(text,extra=""){return el("span","pill "+extra,text)}
function empty(text){return el("p","empty",text)}
function heading(title,note){const h=el("div","section-heading");h.append(el("h2","",title));if(note)h.append(el("span","annotation",note));return h}
function panel(title,note){const p=el("section","section-body");if(title)p.append(heading(title,note));return p}
function raw(section){const d=el("details","source-raw");d.append(el("summary","","Pełny odczyt tej części Librusa"),el("div","raw-text",section.text||"Brak treści."),safeLink(section.url,"Otwórz w Librusie ↗"));return d}
function navigate(id){current=id;query="";render();$("main").focus({preventScroll:true});window.scrollTo({top:0,behavior:"instant"})}
function getDocuments(){return Object.values(data.accounts).flatMap(a=>[...(a.messages||[]),...(a.announcements||[])])}
function openSource(id,fallback){const m=getDocuments().find(m=>m.id===id);if(m){current=m.kind==="announcement"?"announcements":"messages";selected=m.child;query="";render();const d=Array.from(document.querySelectorAll(".document")).find(x=>x.dataset.id===id);if(d){d.open=true;d.scrollIntoView({block:"start",behavior:"smooth"})}}else navigate(fallback||"dates")}
function render(){
 if(!data)return;
 $("children").replaceChildren();
 [["all","Oboje"],...Object.values(data.accounts).map(a=>[a.child,a.name])].forEach(([id,label])=>{const b=button(label,()=>{selected=id;query="";render()});b.setAttribute("aria-pressed",String(selected===id));$("children").append(b)});
 $("updated").textContent="Odczyt: "+datePL(data.collected_at,{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"});
 $("health").replaceChildren();
 const bad=Object.values(data.accounts).filter(a=>a.status!=="ok");
 if(bad.length){const n=el("div","notice");n.append(el("p","","Nie udało się odświeżyć konta: "+bad.map(a=>a.name).join(", ")+". Poniżej ostatni poprawny odczyt."));$("health").append(n)}
 if(Date.now()-new Date(data.collected_at).getTime()>26*3600000){$("health").append(el("div","notice","Raport ma ponad dobę. Kolejny odczyt może wymagać uruchomienia komputera z Codexem. Sprawdź datę przy danych."))}
 $("nav").replaceChildren();
 sections.forEach(([id,label],i)=>{const b=button("",()=>navigate(id));b.append(el("span","",String(i+1).padStart(2,"0")),el("span","",label));if(id===current)b.setAttribute("aria-current","page");$("nav").append(b)});
 const spec=sections.find(x=>x[0]===current), hero=el("header","section-hero"),copy=el("div");
 copy.append(el("p","eyebrow","Promenada / "+spec[1]),el("h1","",spec[2]),el("p","",spec[3]));
 const img=el("img");img.src="./assets/"+current+".webp";img.alt="";img.width=360;img.height=360;hero.append(copy,img);
 $("main").replaceChildren(hero);
 ({overview:overview,messages:documents,announcements:documents,timetable:timetable,dates:dates,grades:grades,attendance:attendance,notes:simple,homework:homework,achievements:simple}[current])();
}
function allActions(){return (data.digest?.actions||[]).filter(x=>selected==="all"||x.child===selected)}
function actionRow(a){
 const row=el("article","action-row"),date=el("div","action-date",a.date?datePL(a.date,{day:"numeric",month:"short"}):a.when||"Do sprawdzenia");
 date.append(el("small","",a.date?datePL(a.date,{weekday:"long"}):"Bez terminu"));
 const body=el("div");body.append(pill(name(a.child)),pill(a.kind||"Informacja","violet"),el("h3","",a.title),el("p","",a.text));
 if(a.source_id)body.append(button("Przeczytaj źródło ↗",()=>openSource(a.source_id,a.section),"text-button"));
 else if(a.section)body.append(button("Zobacz szczegóły ↗",()=>navigate(a.section),"text-button"));
 row.append(date,body);return row;
}
function overview(){
 const p=panel("Na najbliższe dni","Z wiadomości i terminarza");
 const actions=allActions().filter(a=>!a.date||a.date>=dayISO()).sort((a,b)=>(a.date||"9999").localeCompare(b.date||"9999"));
 if(actions.length)actions.forEach(a=>p.append(actionRow(a)));else p.append(empty("W tym raporcie nie ma nowych spraw z przyszłym terminem."));
 $("main").append(p);
 const bottom=el("div","overview-bottom"), n=chosen().reduce((s,a)=>s+(a.messages||[]).length,0);
 const recent=panel("Ze szkolnej poczty");recent.append(el("div","mini-count",String(n)),el("p","annotation","wiadomości w połączonym archiwum"));
 chosen().flatMap(a=>a.messages||[]).sort((a,b)=>b.date.localeCompare(a.date)).slice(0,3).forEach(m=>{const row=el("div","timeline-row");row.append(pill(name(m.child)),el("p","",m.title),button("Czytaj wiadomość ↗",()=>openSource(m.id),"text-button"));recent.append(row)});
 const shelves=panel("Zajrzyj dalej");
 [["timetable","Plan całego tygodnia"],["attendance","Frekwencja i zwolnienia"],["grades","Oceny i opisy postępów"]].forEach(([id,label])=>{const row=el("div","jump"),img=el("img");img.src="./assets/"+id+".webp";img.alt="";img.loading="lazy";row.append(img,button(label,()=>navigate(id)));shelves.append(row)});
 bottom.append(recent,shelves);$("main").append(bottom);
 const notes=(data.digest?.observations||[]).filter(a=>selected==="all"||a.child===selected);
 if(notes.length){const p=panel("Dobrze wiedzieć","Stan z ostatniego odczytu");notes.forEach(a=>p.append(actionRow(a)));$("main").append(p)}
}
function richText(text){
 const p=el("p");const regex=/https?:\/\/[^\s<>"')]+/g;let last=0;
 for(const m of text.matchAll(regex)){p.append(document.createTextNode(text.slice(last,m.index)));p.append(safeLink(m[0],m[0]));last=m.index+m[0].length}p.append(document.createTextNode(text.slice(last)));return p;
}
function attachment(f){
 if(!f.base64){const p=el("div","notice");p.append(el("p","","Załącznik niedostępny: "+f.name));if(f.url)p.append(safeLink(f.url,"Sprawdź w Librusie ↗"));return p}
 return button("Pobierz · "+f.name+" ("+Math.ceil(f.size/1024)+" KB)",()=>{
 const bytes=Uint8Array.from(atob(f.base64),c=>c.charCodeAt(0)),blob=new Blob([bytes],{type:"application/octet-stream"}),url=URL.createObjectURL(blob),a=el("a");a.href=url;a.download=(f.name||"zalacznik").replace(/[\/\\\u0000-\u001f]/g,"_");document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500)
 },"attachment");
}
function doc(m){
 const d=el("details","document");d.dataset.id=m.id;const s=el("summary");
 s.append(pill(name(m.child)),el("span","doc-meta",datePL(m.date)),el("h3","doc-title",m.title),el("p","doc-meta",m.sender));
 const body=el("div","doc-content");body.append(richText(m.text||"Brak treści."));(m.attachments||[]).forEach(f=>body.append(attachment(f)));body.append(safeLink(m.url,"Oryginał w Librusie ↗"));d.append(s,body);return d;
}
function documents(){
 const docs=chosen().flatMap(a=>a[current]||[]).sort((a,b)=>b.date.localeCompare(a.date));
 const p=panel(current==="messages"?"Połączona skrzynka":"Tablica ogłoszeń","Liczba wpisów: "+docs.length), label=el("label","search-label","Szukaj w temacie, treści lub autorze");label.htmlFor="search";
 const input=el("input","search");input.id="search";input.type="search";input.placeholder="Wpisz słowo lub nazwisko";input.value=query;
 const list=el("div");const refreshList=()=>{const q=input.value.trim().toLocaleLowerCase("pl");query=input.value;const filtered=docs.filter(m=>(m.title+" "+m.text+" "+m.sender).toLocaleLowerCase("pl").includes(q));list.replaceChildren(...filtered.map(doc));if(!filtered.length)list.append(empty("Nie znaleziono pasujących wpisów."))};
 input.addEventListener("input",refreshList);refreshList();p.append(label,input,list);$("main").append(p);
}
function timetable(){
 const p=panel("Tydzień w szkole","Godziny lekcji, bez dojazdów");
 chosen().forEach(a=>{const sec=a.sections?.timetable;if(!sec){p.append(empty(a.name+": brak odczytu planu."));return}const child=el("section","child-section");child.append(el("h3","child-title",a.name));
 (sec.days||[]).forEach(day=>{
 const d=el("details","week-day"),sum=el("summary"),title=el("h4","",day.label),active=day.lessons.filter(x=>!x.text.toLowerCase().includes("odwołane"));
 const start=active[0]?.time.match(/\d\d:\d\d/g)?.[0], end=active.at(-1)?.time.match(/\d\d:\d\d/g)?.[1];
 sum.append(title,el("span","day-times",start&&end?start+"–"+end:"Brak aktywnych lekcji"));d.append(sum);
 if(day.lessons.length===0)d.append(empty("W planie nie ma zajęć na ten dzień."));
 day.lessons.forEach(lesson=>{const row=el("div","lesson");row.append(el("time","",lesson.time.replace(/\s*-\s*/,"–")));const txt=el("div");const canceled=lesson.text.includes("odwołane");txt.append(el("span",canceled?"canceled":"",lesson.text));if(canceled)txt.append(el("small","","Lekcja odwołana"));if(lesson.details?.length)txt.append(el("small","",lesson.details.join("\n")));row.append(txt);d.append(row)});
 child.append(d);
 });
 child.append(safeLink(sec.url,"Plan w Librusie ↗"));p.append(child);
 });
 p.append(el("p","annotation","Odwołana lekcja nie przesądza o pobycie w domu. Wycieczki i zwolnienia sprawdzisz w frekwencji."));$("main").append(p);
}
function dates(){
 const actions=allActions().filter(a=>a.date).sort((a,b)=>a.date.localeCompare(b.date));
 if(actions.length){const p=panel("Z wiadomości i ustaleń");actions.forEach(a=>p.append(actionRow(a)));$("main").append(p)}
 const p=panel("Terminarz Librusa","Pełny odczyt dostępnego miesiąca");chosen().forEach(a=>{
 const sec=a.sections?.dates;const wrap=el("section","child-section");wrap.append(el("h3","child-title",a.name));if(!sec?.events?.length)wrap.append(empty("Brak wpisów w odczytanym terminarzu."));
 [...(sec?.events||[])].sort((a,b)=>a.date.localeCompare(b.date)).forEach(e=>{const row=el("article","timeline-row");row.append(pill(datePL(e.date)),el("h3","",e.text),el("p","",e.details));wrap.append(row)});
 if(sec)wrap.append(safeLink(sec.url,"Terminarz w Librusie ↗"));p.append(wrap)
 });$("main").append(p);
}
function grades(){
 const p=panel("Oceny według przedmiotów","Rozwiń ocenę, aby poznać szczegóły");
 chosen().forEach(a=>{
 const sec=a.sections?.grades;const wrap=el("section","child-section");wrap.append(el("h3","child-title",a.name));if(!sec){wrap.append(empty("Nie udało się odczytać ocen."));p.append(wrap);return}
 if(!(sec.subjects||[]).some(s=>s.grades.length))wrap.append(empty("W Librusie nie ma jeszcze ocen bieżących."));
 const table=el("table"),thead=el("thead"),tr=el("tr");["Przedmiot","Okres 1","Okres 2","Roczna"].forEach(s=>tr.append(el("th","",s)));thead.append(tr);table.append(thead);const body=el("tbody");
 (sec.subjects||[]).forEach(s=>{const row=el("tr");row.append(el("td","",s.subject));[1,2].forEach(term=>{const td=el("td"),grades=s.grades.filter(g=>g.term===term);if(!grades.length)td.append(el("span","muted","Brak ocen"));grades.forEach(g=>{const d=el("details","grade");d.append(el("summary","",g.value),el("p","",g.details||"Brak dodatkowego opisu."));td.append(d)});const final=term===1?s.final1:s.final2;if(final&&final!=="-")td.append(el("p","annotation","Śródroczna: "+final));row.append(td)});row.append(el("td","",s.year==="-"?"—":s.year));body.append(row)});
 table.append(body);const scroll=el("div","table-wrap");scroll.append(table);wrap.append(scroll);
 if(sec.descriptive?.length){const h=el("h3","child-title","Oceny opisowe");h.classList.add("source-raw");wrap.append(h);sec.descriptive.forEach(d=>{const row=el("article","timeline-row");row.append(el("h4","",d.area),el("p","muted",d.text.trim()||"Brak wpisów."));if(d.details.length)row.append(el("p","",d.details.join("\n")));wrap.append(row)})}
 wrap.append(raw(sec));p.append(wrap);
 });p.append(el("p","annotation","Średnie wyłączone przez szkołę nie są wyliczane przez Promenadę."));$("main").append(p);
}
function attendance(){
 const labels={nb:"Nieobecności",u:"Usprawiedliwione",sp:"Spóźnienia",zw:"Zwolnienia"};
 const p=panel("Wpisy frekwencji","Jednostka: godzina lekcyjna");chosen().forEach(a=>{
 const sec=a.sections?.attendance;const wrap=el("section","child-section");wrap.append(el("h3","child-title",a.name));if(!sec){wrap.append(empty("Brak odczytu frekwencji."));p.append(wrap);return}
 const stats=el("div","stats");Object.entries(labels).forEach(([code,label])=>{const stat=el("div","stat");stat.append(el("b","",String(sec.counts?.[code]||0)),el("span","",label));stats.append(stat)});wrap.append(stats);
 if(!sec.entries?.length)wrap.append(empty("Brak wpisów w odczytanym widoku. To nie jest potwierdzenie stuprocentowej obecności."));
 const byDate=Object.groupBy?Object.groupBy(sec.entries||[],e=>e.date):(sec.entries||[]).reduce((o,e)=>((o[e.date]??=[]).push(e),o),{});
 Object.entries(byDate).sort(([a],[b])=>b.localeCompare(a)).forEach(([date,entries])=>{const d=el("details","attendance-group"),sum=el("summary");sum.append(el("strong","",datePL(date,{weekday:"short",day:"numeric",month:"long"})),el("span","annotation","Wpisy: "+entries.length));d.append(sum);entries.forEach(e=>{const row=el("div","attendance-record");row.append(el("strong","",labels[e.code]||e.code),el("p","",e.details));d.append(row)});wrap.append(d)});
 wrap.append(raw(sec));p.append(wrap)
 });$("main").append(p);
}
function simple(){
 const p=panel(current==="notes"?"Uwagi ze szkoły":"Osiągnięcia w dzienniku");chosen().forEach(a=>{const sec=a.sections?.[current],wrap=el("section","child-section");wrap.append(el("h3","child-title",a.name));if(!sec)wrap.append(empty("Brak odczytu tej sekcji."));else if(sec.empty)wrap.append(empty(current==="notes"?"Brak uwag w Librusie.":"Brak szczególnych osiągnięć wpisanych w Librusie."));else wrap.append(el("div","raw-text",sec.text));if(sec)wrap.append(safeLink(sec.url,"Otwórz w Librusie ↗"));p.append(wrap)});$("main").append(p);
}
function homework(){
 const p=panel("Zadania i przygotowania");chosen().forEach(a=>{
 const sec=a.sections?.homework,wrap=el("section","child-section");wrap.append(el("h3","child-title",a.name));
 const events=(a.sections?.dates?.events||[]).filter(e=>/praca domowa|zadani|lektur/i.test(e.text+" "+e.details));
 events.forEach(e=>{const row=el("article","timeline-row");row.append(pill("Terminarz"),pill(datePL(e.date),"violet"),el("h3","",e.text),el("p","",e.details));wrap.append(row)});
 if(sec){if(/Brak wpisów/i.test(sec.text))wrap.append(empty("Moduł „Zadania domowe” nie zawiera wpisów."));else wrap.append(el("div","raw-text",sec.text));wrap.append(safeLink(sec.url,"Zadania w Librusie ↗"))}else wrap.append(empty("Brak odczytu modułu zadań."));p.append(wrap)
 });$("main").append(p);
}
function fromB64(s){return Uint8Array.from(atob(s),c=>c.charCodeAt(0))}
async function fetchReport(){const r=await fetch("./report.enc.json?t="+Date.now(),{cache:"no-store",credentials:"omit",referrerPolicy:"no-referrer"});if(!r.ok)throw Error("network");const envelope=await r.json();if(envelope.v!==1||envelope.iterations!==600000)throw Error("format");return envelope}
async function decrypt(envelope,material){
 const key=await crypto.subtle.deriveKey({name:"PBKDF2",salt:fromB64(envelope.salt),iterations:envelope.iterations,hash:"SHA-256"},material,{name:"AES-GCM",length:256},false,["decrypt"]);
 const plain=await crypto.subtle.decrypt({name:"AES-GCM",iv:fromB64(envelope.iv),additionalData:new TextEncoder().encode("promenada-report-v1")},key,fromB64(envelope.ciphertext));
 const parsed=JSON.parse(new TextDecoder().decode(plain));if(parsed.schema!==1||!parsed.accounts)throw Error("format");return parsed;
}
$("unlock-form").addEventListener("submit",async e=>{
 e.preventDefault();$("unlock").disabled=true;$("gate-status").textContent="Otwieram dziennik…";
 try{
 const password=$("password").value.trim();if(!password)throw Error("empty");
 const material=await crypto.subtle.importKey("raw",new TextEncoder().encode(password),"PBKDF2",false,["deriveKey"]);
 let envelope;try{envelope=await fetchReport()}catch{throw Error("network")}
 data=await decrypt(envelope,material);keyMaterial=material;$("password").value="";$("gate-status").textContent="";$("gate").hidden=true;$("journal").hidden=false;$("lock").hidden=false;activity=Date.now();render();$("main").focus({preventScroll:true});
 }catch(e){$("gate-status").textContent=e.message==="network"?"Nie udało się pobrać raportu. Sprawdź połączenie i spróbuj ponownie.":"Hasło nie otwiera dziennika. Sprawdź je i spróbuj ponownie."}
 finally{$("unlock").disabled=false}
});
$("show-password").addEventListener("change",e=>{$("password").type=e.target.checked?"text":"password"});
function lock(){data=null;keyMaterial=null;selected="all";current="overview";query="";$("main").replaceChildren();$("children").replaceChildren();$("nav").replaceChildren();$("health").replaceChildren();$("updated").textContent="";$("journal").hidden=true;$("gate").hidden=false;$("lock").hidden=true;$("password").type="password";$("show-password").checked=false;$("password").value="";window.scrollTo({top:0,behavior:"instant"})}
$("lock").addEventListener("click",lock);
$("refresh").addEventListener("click",async()=>{if(!keyMaterial)return;$("refresh").disabled=true;$("refresh").textContent="Wczytuję…";try{const fresh=await decrypt(await fetchReport(),keyMaterial);if(keyMaterial){data=fresh;render()}}catch{$("health").replaceChildren(el("div","notice","Nie udało się wczytać nowszego raportu. Oglądasz ostatnio otwartą wersję."))}finally{$("refresh").disabled=false;$("refresh").textContent="Wczytaj nowszy raport"}});
["pointerdown","keydown"].forEach(type=>document.addEventListener(type,()=>activity=Date.now(),{passive:true}));
setInterval(()=>{if(data&&Date.now()-activity>30*60*1000)lock()},60000);
window.addEventListener("pagehide",lock);
