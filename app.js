"use strict";
const attachmentUrls=new Set(), attachmentRequests=new Set(), reportRequests=new Set();
function cancelReportRequests(){for(const request of reportRequests)request.abort();reportRequests.clear()}
let attachmentGeneration=0, sessionGeneration=0;
function releaseAttachments(){
 attachmentGeneration++;
 for(const request of attachmentRequests)request.abort();attachmentRequests.clear();
 for(const url of attachmentUrls)URL.revokeObjectURL(url);attachmentUrls.clear();
}
let data=null, keyMaterial=null, selected=null, current="overview", query="", activity=Date.now();
const $=id=>document.getElementById(id);
const sections=[
["overview","Przegląd","Szkoła w jednym miejscu.","Najważniejsze sprawy, nadchodzące terminy i pełny obraz szkolnego tygodnia."],
["messages","Wiadomości","Słowo ze szkoły.","Skrzynka wybranego dziecka. Pełna treść wiadomości i załączniki, uporządkowane od najnowszych."],
["announcements","Ogłoszenia","Na szkolnej tablicy.","Komunikaty szkół i nauczycieli. Każdy z datą, autorem i wskazaniem dziecka."],
["timetable","Plan lekcji","Rytm tygodnia.","Godziny od pierwszej do ostatniej lekcji. Rozwiń dzień, aby zobaczyć przedmioty, sale i zmiany."],
["dates","Terminy","Warto pamiętać.","Terminarz z Librusa oraz daty odczytane z wiadomości. Źródło jest zawsze pod ręką."],
["grades","Oceny","Małe i duże postępy.","Oceny bieżące i opisowe. Szczegóły wpisów dokładnie tak, jak udostępnia je szkoła."],
["attendance","Frekwencja","Obecność ma znaczenie.","Wpisy o obecności, zwolnieniach i spóźnieniach. Liczymy wpisy, nie domyślamy się przyczyn."],
["notes","Uwagi","Spojrzenie nauczyciela.","Uwagi i spostrzeżenia ze szkoły, zebrane osobno dla każdego dziecka."],
["homework","Zadania","Na spokojne popołudnie.","Zadania z modułu prac domowych i z terminarza. Także lektury i dłuższe przygotowania."],
["achievements","Osiągnięcia","Powody do dumy.","Szczególne osiągnięcia zapisane przez szkołę. Miejsce na to, co warte zapamiętania."]
];

let reviewState={read:{},done:{},priority:{}}, attentionFilter="all";
try{const saved=JSON.parse(localStorage.getItem("promenada-review-v1")||"null");if(saved&&typeof saved==="object")reviewState={read:saved.read||{},done:saved.done||{},priority:saved.priority||{}}}catch{}
function saveReview(){try{localStorage.setItem("promenada-review-v1",JSON.stringify(reviewState))}catch{}}
function isNew(item){return Boolean(item?.revision&&!reviewState.read[item.revision])}
function isDone(a){return Boolean(a.id&&reviewState.done[a.id]===a.revision)}
function priority(item){
 if(reviewState.priority[item.revision])return reviewState.priority[item.revision];
 if(item.kind==="Dla chętnych")return "info";
 if(item.date&&item.id&&!["message","announcement"].includes(item.kind)){const days=(new Date(item.date+"T12:00:00")-new Date(dayISO()+"T12:00:00"))/86400000;if(days<=2)return "urgent"}
 if(item.kind==="message"||item.kind==="announcement"){
  const related=(data.digest?.actions||[]).filter(a=>a.source_id===item.id);
  if(related.some(a=>priority(a)==="urgent"))return "urgent";
  if(related.length)return "todo";
  if(/proszę o|należy|proszę przynieść|termin składania|prosimy o/i.test(item.text||""))return "todo";
  return "info";
 }
 return item.priority||"todo";
}
const priorityLabel={urgent:"Pilne",todo:"Do dopilnowania",info:"Informacyjne"};
function priorityPill(item){const p=priority(item);return pill(priorityLabel[p],"priority-"+p)}
function markRead(item){if(!item?.revision)return;reviewState.read[item.revision]=new Date().toISOString();saveReview();render()}
function toggleDone(a){if(isDone(a))delete reviewState.done[a.id];else{reviewState.done[a.id]=a.revision;reviewState.read[a.revision]=new Date().toISOString()}saveReview();render()}
function sectionHasData(a,id){
 const sec=a.sections?.[id];if(!sec)return false;
 if(id==="grades")return (sec.subjects||[]).some(s=>s.grades.length)||(sec.descriptive||[]).some(d=>d.text.trim());
 if(id==="attendance")return sec.entries?.length>0;
 if(id==="notes"||id==="achievements")return !sec.empty;
 if(id==="homework")return !/Brak wpisów/.test(sec.text)||(a.sections?.dates?.events||[]).some(e=>/praca domowa|lektur/i.test(e.text+" "+e.details));
 if(id==="dates")return sec.events?.length>0;
 if(id==="timetable")return sec.days?.some(d=>d.lessons.length);
 return false;
}
function newCount(id){
 if(["messages","announcements"].includes(id))return chosen().flatMap(a=>a[id]||[]).filter(isNew).length;
 if(id==="overview")return allActions().filter(a=>isNew(a)&&!isDone(a)).length;
 return chosen().filter(a=>sectionHasData(a,id)&&isNew(a.sections[id])).length;
}
function attentionBar(){
 const bar=el("div","attention-bar");
 [["all","Otwarte"],["urgent","Pilne"],["new","Nowe"],["done","Zrobione"]].forEach(([id,title])=>{const b=button(title,()=>{attentionFilter=id;render()},"attention-button");b.setAttribute("aria-pressed",String(attentionFilter===id));bar.append(b)});
 return bar;
}

function sectionReview(sec){const box=el("div","section-review");if(isNew(sec)){box.append(pill("Nowe dane","new"),button("Oznacz jako przejrzane",()=>markRead(sec),"text-button"))}else box.append(el("span","annotation","Przejrzane na tym urządzeniu"));return box}

function el(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n}
function button(label,fn,cls=""){const n=el("button",cls,label);n.type="button";n.addEventListener("click",fn);return n}
function name(key){return data?.accounts[key]?.name||""}
function chosen(){return Object.values(data.accounts).filter(a=>a.child===selected)}
function selectChild(id){
 if(!Object.values(data.accounts).some(a=>a.child===id))return;
 selected=id;query="";attentionFilter="all";documentFilter="all";
 render();$("main").focus({preventScroll:true});window.scrollTo({top:0,behavior:"instant"});
}
function datePL(s,options={day:"numeric",month:"long"}){if(!s)return "";const d=new Date(s.length===10?s+"T12:00:00":s.replace(" ","T"));return Number.isNaN(+d)?s:new Intl.DateTimeFormat("pl-PL",{timeZone:"Europe/Warsaw",...options}).format(d)}
function dayISO(){return new Intl.DateTimeFormat("sv-SE",{timeZone:"Europe/Warsaw"}).format(new Date())}
function safeLink(url,label){const a=el("a","source-link",label);try{const u=new URL(url);if(!["https:","http:"].includes(u.protocol))return el("span","muted",label);a.href=u.href;a.target="_blank";a.rel="noopener noreferrer";return a}catch{return el("span","muted",label)}}
function pill(text,extra=""){return el("span","pill "+extra,text)}
function empty(text){return el("p","empty",text)}
function heading(title,note){const h=el("div","section-heading");h.append(el("h2","",title));if(note)h.append(el("span","annotation",note));return h}
function panel(title,note){const p=el("section","section-body");if(title)p.append(heading(title,note));return p}
function raw(section){const d=el("details","source-raw");d.append(el("summary","","Pełny odczyt tej części Librusa"),el("div","raw-text",section.text||"Brak treści."),safeLink(section.url,"Otwórz w Librusie ↗"));return d}
function navigate(id){current=id;query="";attentionFilter="all";documentFilter="all";render();$("main").focus({preventScroll:true});window.scrollTo({top:0,behavior:"instant"})}
function getDocuments(){return chosen().flatMap(a=>[...(a.messages||[]),...(a.announcements||[])])}
function openSource(id,fallback){const m=getDocuments().find(m=>m.id===id);if(m){current=m.kind==="announcement"?"announcements":"messages";selected=m.child;query="";render();const d=Array.from(document.querySelectorAll(".document")).find(x=>x.dataset.id===id);if(d){d.open=true;d.scrollIntoView({block:"start",behavior:"smooth"})}}else navigate(fallback||"dates")}

let documentFilter="all";
const compactTitles={overview:["Sprawy na teraz","Najważniejsze informacje, w krótszym widoku."],messages:["Wiadomości","Pełna treść po rozwinięciu wiadomości."],announcements:["Ogłoszenia","Komunikaty szkoły wybranego dziecka."],timetable:["Plan lekcji","Dotknij godzin, aby zobaczyć lekcje."],dates:["Terminy","Daty z wiadomości i terminarza."],grades:["Oceny","Bieżące oceny i opisy postępów."],attendance:["Frekwencja","Nieobecności, zwolnienia i spóźnienia."],notes:["Uwagi","Wpisy i spostrzeżenia nauczycieli."],homework:["Zadania","Prace domowe, lektury i przygotowania."],achievements:["Osiągnięcia","Sukcesy zapisane przez szkołę."],more:["Pozostałe działy","Wszystkie szkolne sprawy są pod ręką."]};
const primarySections=["overview","messages","timetable","grades"];
function uiIcon(key){
 const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
 svg.setAttribute("viewBox","0 0 24 24");svg.setAttribute("fill","none");svg.setAttribute("stroke","currentColor");svg.setAttribute("stroke-width","1.6");svg.setAttribute("stroke-linecap","round");svg.setAttribute("stroke-linejoin","round");svg.setAttribute("aria-hidden","true");svg.classList.add("nav-icon");
 const paths={
 overview:'<rect x="4" y="3" width="16" height="18" rx="3"/><path d="m8 9 1.5 1.5L12 8M14 10h3m-9 5h9"/>',
 messages:'<rect x="3" y="5" width="18" height="14" rx="3"/><path d="m4 7 8 6 8-6"/>',
 timetable:'<rect x="4" y="5" width="16" height="16" rx="3"/><path d="M8 3v4m8-4v4M4 10h16m-12 4h2m4 0h2m-8 4h2"/>',
 grades:'<path d="M5 20V7a2 2 0 0 1 2-2h12v15H7a2 2 0 0 1 0-4h12"/><path d="m10 11 1.5 1.5L15 9"/>',
 more:'<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
 announcements:'<path d="m3 10 15-5v14L3 14zm4 5 1 5h3l-1-4m11-9v10"/>',
 dates:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 attendance:'<path d="m5 12 4 4L19 6"/><path d="M4 4h5M4 20h16"/>',
 notes:'<path d="M5 4h14v13H9l-4 4zM8 8h8m-8 4h6"/>',
 homework:'<path d="M4 20h16M6 16l1-4L17 2l4 4-10 10zm9-12 4 4"/>',
 achievements:'<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z"/>'
 };
 svg.innerHTML=paths[key]||paths.more;return svg;
}
function childTone(key){
 const identity=(key+" "+name(key)).toLocaleLowerCase("pl");
 if(/\b(witek|witold)\b/.test(identity))return "blue";
 if(/\b(kostek|konstanty)\b/.test(identity))return "olive";
 // Keep a stable colour for other/synthetic accounts, independent of report order.
 return Array.from(String(key)).reduce((sum,c)=>sum+c.codePointAt(0),0)%2?"blue":"olive";
}
function childTag(key){const tag=el("span","child-tag",name(key));tag.dataset.childTone=childTone(key);return tag}
function shortDate(s){return datePL(s,{day:"numeric",month:"short"})}
function lessonCount(n){return n+" "+(n===1?"lekcja":n%10>=2&&n%10<=4&&!(n%100>=12&&n%100<=14)?"lekcje":"lekcji")}
function lessonSpan(day){
 const lessons=day?.lessons||[],active=lessons.filter(x=>!x.text.toLowerCase().includes("odwołane"));
 const first=active[0]?.time.match(/\d\d:\d\d/g)?.[0],last=active.at(-1)?.time.match(/\d\d:\d\d/g)?.[1];
 return {active,span:first&&last?first+"–"+last:"Brak lekcji"};
}
function todayPlan(){
 const p=panel("Dziś w planie",shortDate(dayISO()));
 chosen().forEach(a=>{
  const day=a.sections?.timetable?.days?.find(d=>d.label.includes(dayISO()));
  const trip=(a.sections?.attendance?.entries||[]).some(e=>e.date===dayISO()&&e.details?.includes("Czy wycieczka: Tak"));
  const time=trip?"Wycieczka · sprawdź godziny":day?lessonSpan(day).span:"Brak dnia w odczycie";
  const b=button("",()=>{selected=a.child;navigate("timetable")},"plan-glance");b.append(el("strong","",a.name),el("span","",time));p.append(b);
 });return p;
}
function moreSections(){
 const p=panel("Działy dziennika"),list=el("div","more-list");
 const subtitles={announcements:"Tablica ogłoszeń",dates:"Sprawdziany, terminy i wydarzenia",attendance:"Obecność i zwolnienia",notes:"Informacje od nauczycieli",homework:"Przygotowania i prace domowe",achievements:"Szczególne osiągnięcia"};
 sections.filter(([id])=>!primarySections.includes(id)).forEach(([id,title])=>{
  const b=button("",()=>navigate(id),"more-row"),text=el("span");text.append(el("strong","",title),el("small","",subtitles[id]||""));b.append(uiIcon(id),text);const n=newCount(id);if(n)b.append(el("span","nav-count",String(n)));else b.append(el("span","row-chevron"));list.append(b);
 });p.append(list);$("main").append(p);
}

function missedCollection(){
 const parts=d=>Object.fromEntries(new Intl.DateTimeFormat("sv-SE",{timeZone:"Europe/Warsaw",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).formatToParts(d).filter(p=>p.type!=="literal").map(p=>[p.type,p.value]));
 const now=parts(new Date()),today=now.year+"-"+now.month+"-"+now.day,minute=+now.hour*60+(+now.minute);
 // Allow the bounded retries to finish before showing a missed-window warning.
 const target=minute>=1110?"18:00":minute>=420?"06:30":null;
 return chosen().some(a=>{
  const timestamp=new Date(a.checked_at||data.collected_at);
  if(!Number.isFinite(timestamp.getTime()))return true;
  const read=parts(timestamp),readAt=read.year+"-"+read.month+"-"+read.day+"T"+read.hour+":"+read.minute;
  return target?readAt<today+"T"+target:Date.now()-timestamp.getTime()>15*3600000;
 });
}
function renderHealth(){
 $("health").replaceChildren();
 const bad=chosen().filter(a=>a.status!=="ok");
 if(bad.length){const n=el("div","notice");n.append(el("p","","Nie udało się odświeżyć konta: "+bad.map(a=>a.name).join(", ")+". Poniżej ostatni poprawny odczyt."));$("health").append(n)}
 if(missedCollection()){$("health").append(el("div","notice","Brakuje aktualnego raportu z ostatniej pory odczytu. Wyświetlane dane są starsze."))}
}
function render(){
 if(!data)return;
 const expanded=new Set(Array.from(document.querySelectorAll("details[open][data-id]")).map(d=>d.dataset.id));
 releaseAttachments();
 $("children").replaceChildren();
 const accounts=Object.values(data.accounts);
 if(!accounts.some(a=>a.child===selected))selected=accounts[0]?.child??null;
 $("journal").dataset.childTone=childTone(selected);
 accounts.map(a=>[a.child,a.name]).forEach(([id,label])=>{const b=button(label,()=>selectChild(id));b.dataset.childTone=childTone(id);b.setAttribute("aria-label","Pokaż dziennik: "+label);b.setAttribute("aria-pressed",String(selected===id));$("children").append(b)});
 $("children").hidden=accounts.length===1;
 $("updated").textContent="Odczyt: "+datePL(data.collected_at,{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"});
 renderHealth();
 $("nav").replaceChildren();
 const navNames={overview:"Sprawy",messages:"Poczta",timetable:"Plan",grades:"Oceny"};
 sections.forEach(([id,label])=>{
  const b=button("",()=>navigate(id),primarySections.includes(id)?"nav-primary":"nav-secondary");b.dataset.section=id;
  b.append(uiIcon(id),el("span","nav-label",navNames[id]||label));b.setAttribute("aria-label",label);
  const n=newCount(id);if(n)b.append(el("span","nav-count",String(n)));if(id===current)b.setAttribute("aria-current","page");$("nav").append(b);
 });
 const more=button("",()=>navigate("more"),"nav-more");more.setAttribute("aria-label","Więcej działów");more.append(uiIcon("more"),el("span","nav-label","Więcej"));const otherNew=sections.filter(([id])=>!primarySections.includes(id)).reduce((total,[id])=>total+newCount(id),0);if(otherNew)more.append(el("span","nav-count",String(otherNew)));if(!primarySections.includes(current))more.setAttribute("aria-current","page");$("nav").append(more);
 const spec=compactTitles[current]||compactTitles.overview,hero=el("header","section-hero");
 hero.append(el("span","child-context","Dziennik: "+name(selected)),el("h1","",spec[0]),el("p","",spec[1]));$("main").replaceChildren(hero);
 ({overview,documents,messages:documents,announcements:documents,timetable,dates,grades,attendance,notes:simple,homework,achievements:simple,more:moreSections}[current])();
 document.querySelectorAll("details[data-id]").forEach(d=>{if(expanded.has(d.dataset.id))d.open=true});
}

function allActions(){return (data.digest?.actions||[]).filter(x=>x.child===selected)}
function actionRow(a){
 const row=el("details","task-row");row.dataset.id=a.id||a.source_id||a.title;
 const sum=el("summary"),date=el("span","task-when"+(!a.date?" undated":""));
 if(a.date)date.append(el("span","",datePL(a.date,{day:"numeric"})),el("small","",datePL(a.date,{month:"short"})));
 else date.append(el("span","",a.when||"Bez daty"));
 const copy=el("div"),meta=el("div","row-meta");meta.append(childTag(a.child),priorityPill(a));if(isNew(a)&&!isDone(a))meta.append(pill("Nowe","new"));if(a.date&&a.date<dayISO()&&!isDone(a))meta.append(pill("Po terminie","priority-urgent"));
 copy.append(meta,el("h3","task-title",a.title));sum.append(date,copy,el("span","row-chevron"));
 const content=el("div","task-content");content.append(el("p","",a.text));const controls=el("div","row-actions");
 if(a.source_id)controls.append(button("Przeczytaj źródło ↗",()=>openSource(a.source_id,a.section),"text-button"));
 else if(a.section)controls.append(button("Zobacz szczegóły ↗",()=>navigate(a.section),"text-button"));
 if(a.id)controls.append(button(isDone(a)?"Zrobione · cofnij":"Oznacz jako zrobione",()=>toggleDone(a),"task-check"));
 content.append(controls);row.append(sum,content);if(isDone(a))row.classList.add("completed");return row;
}

function overview(){
 const grid=el("div","overview-grid"),p=panel("Do dopilnowania",allActions().filter(a=>!isDone(a)).length+" otwartych");p.append(attentionBar());
 const ranks={urgent:0,todo:1,info:2};
 const actions=allActions().filter(a=>attentionFilter==="done"?isDone(a):!isDone(a)).filter(a=>attentionFilter==="all"||attentionFilter==="done"||attentionFilter==="new"&&isNew(a)||priority(a)===attentionFilter).sort((a,b)=>ranks[priority(a)]-ranks[priority(b)]||(a.date||"9999").localeCompare(b.date||"9999"));
 if(actions.length)actions.forEach(a=>p.append(actionRow(a)));else p.append(empty("Nie ma spraw pasujących do tego filtra."));
 p.append(el("p","annotation review-note","Rozwiń wiersz, aby przeczytać szczegóły lub oznaczyć sprawę jako zrobioną."));
 const aside=el("div","overview-aside");aside.append(todayPlan());
 const fresh=chosen().flatMap(a=>[...(a.messages||[]),...(a.announcements||[])]).filter(isNew).sort((a,b)=>b.date.localeCompare(a.date)),inbox=panel("Nowe ze szkoły",String(fresh.length));
 if(!fresh.length)inbox.append(empty("Wszystkie treści są przejrzane."));
 fresh.slice(0,4).forEach(m=>{const b=button("",()=>openSource(m.id),"fresh-row"),meta=el("div","row-meta");meta.append(childTag(m.child),el("span","doc-date",shortDate(m.date)));b.append(meta,el("strong","",m.title));inbox.append(b)});
 inbox.append(button("Wszystkie wiadomości ↗",()=>navigate("messages"),"text-button all-messages"));aside.append(inbox);
 const notes=(data.digest?.observations||[]).filter(a=>a.child===selected);
 if(notes.length){const notesPanel=panel("Warto sprawdzić");notes.forEach(a=>notesPanel.append(actionRow(a)));aside.append(notesPanel)}
 grid.append(p,aside);$("main").append(grid);
}

function richText(text){
 const p=el("p");const regex=/https?:\/\/[^\s<>"')]+/g;let last=0;
 for(const m of text.matchAll(regex)){p.append(document.createTextNode(text.slice(last,m.index)));p.append(safeLink(m[0],m[0]));last=m.index+m[0].length}p.append(document.createTextNode(text.slice(last)));return p;
}
// Shared attachment protocol helpers. Keep these in the bundled native web view too.
const REPORT_SITE_ROOT="https://jakiesluchawki.github.io/promenada-dziennik/";
const MAX_REPORT_BYTES=25000000, MAX_ATTACHMENT_BYTES=8000000;
// Endpoint provenance is private client state, never a field supplied by the server.
const reportEnvelopeSchemas=new WeakMap();
function reportScope(report){
 const audience=report.audience===undefined?"parent":report.audience,principal=report.principal===undefined?"parent":report.principal;
 if(audience==="parent"&&principal==="parent")return {audience,principal};
 if(audience==="student"&&typeof principal==="string"&&/^[0-9a-f]{64}$/.test(principal))return {audience,principal};
 throw Error("scope");
}
function validateReportAccess(report,expected){
 if(!report||![1,2].includes(report.schema)||!report.accounts||typeof report.accounts!=="object"||Array.isArray(report.accounts))throw Error("format");
 const scope=reportScope(report),accounts=Object.entries(report.accounts);
 if(!accounts.length)throw Error("scope");
 if(expected&&(scope.audience!==expected.audience||scope.principal!==expected.principal))throw Error("scope");
 if(scope.audience==="student"&&(accounts.length!==1||accounts[0][1]?.role!=="student"))throw Error("scope");
 for(const [accountKey,account] of accounts){
  if(!accountKey||!account||typeof account!=="object"||Array.isArray(account)||(account.child!==undefined&&account.child!==accountKey))throw Error("scope");
  if(scope.audience==="parent"&&account.role!==undefined&&account.role!=="parent")throw Error("scope");
  const documentIDs=new Set();
  for(const source of ["messages","announcements"]){
   if(account[source]!==undefined&&!Array.isArray(account[source]))throw Error("format");
   for(const message of account[source]||[]){
    if(!message||message.child!==accountKey||typeof message.id!=="string"||!message.id.startsWith(accountKey+":")||documentIDs.has(message.id))throw Error("scope");
    documentIDs.add(message.id);
    const kind=source==="messages"?"message":"announcement";
    const files=message.attachments||[];if(!Array.isArray(files))throw Error("format");
    if(files.some(file=>file&&("base64" in file||"encrypted_attachment" in file))&&(message.kind!==kind||!message.id.startsWith(accountKey+":"+kind+":")))throw Error("scope");
   }
  }
 }
 if(scope.audience==="student")for(const item of [...(report.digest?.actions||[]),...(report.digest?.observations||[])])if(item.child!==accounts[0][0])throw Error("scope");
 return report;
}
function strictAttachmentBase64(value,size){
 if(typeof value!=="string"||value.length!==4*Math.ceil(size/3)||!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value))throw Error("format");
 const decoded=Uint8Array.from(atob(value),c=>c.charCodeAt(0));
 if(decoded.length!==size||btoa(String.fromCharCode(...decoded))!==value)throw Error("format");
 return decoded;
}
function validateAttachmentReference(ref){
 if(!ref||Object.keys(ref).sort().join(",")!=="iv,key,path,sha256,size,v"||ref.v!==1||typeof ref.path!=="string"||!/^attachments\/[0-9a-f]{64}\.bin$/.test(ref.path)||typeof ref.sha256!=="string"||!/^[0-9a-f]{64}$/.test(ref.sha256)||!Number.isSafeInteger(ref.size)||ref.size<0||ref.size>MAX_ATTACHMENT_BYTES)throw Error("format");
 return {key:strictAttachmentBase64(ref.key,32),iv:strictAttachmentBase64(ref.iv,12)};
}
function attachmentContext(report,message,index,file){
 validateReportAccess(report);
 const scope=reportScope(report);
 if(![1,2].includes(report.schema)||!Number.isSafeInteger(index)||index<0)throw Error("scope");
 const matches=[];
 for(const [accountKey,account] of Object.entries(report.accounts||{}))for(const source of ["messages","announcements"]){
  const messages=account[source]||[];
  if(messages.includes(message)){
   const kind=source==="messages"?"message":"announcement";
   if(message.child!==accountKey||message.kind!==kind||typeof message.id!=="string"||!message.id.startsWith(accountKey+":"+kind+":")||message.attachments?.[index]!==file||messages.filter(item=>item.id===message.id).length!==1)throw Error("scope");
   matches.push({...scope,accountKey,source,messageId:message.id,attachmentIndex:index});
  }
 }
 if(matches.length!==1)throw Error("scope");
 return matches[0];
}
function attachmentAAD(ref,scope){
 if(!scope||!["parent","student"].includes(scope.audience)||typeof scope.principal!=="string"||typeof scope.accountKey!=="string"||!scope.accountKey||typeof scope.messageId!=="string"||!scope.messageId.startsWith(scope.accountKey+":"+(scope.source==="messages"?"message":"announcement")+":")||!["messages","announcements"].includes(scope.source)||!Number.isSafeInteger(scope.attachmentIndex)||scope.attachmentIndex<0)throw Error("scope");
 reportScope(scope);
 return new TextEncoder().encode(JSON.stringify(["promenada-attachment-v1",scope.audience,scope.principal,scope.accountKey,scope.messageId,scope.attachmentIndex,ref.sha256,ref.size]));
}
function attachmentPaddedSize(size){
 if(!Number.isSafeInteger(size)||size<0||size>MAX_ATTACHMENT_BYTES)throw Error("size");
 return Math.min(MAX_ATTACHMENT_BYTES,Math.max(65536,Math.ceil(size/65536)*65536));
}
function attachmentURL(ref){
 validateAttachmentReference(ref);
 const root=new URL(REPORT_SITE_ROOT),url=new URL(ref.path,root);
 if(url.origin!==root.origin||url.href!==REPORT_SITE_ROOT+ref.path)throw Error("path");
 return url;
}
function checkAttachmentSignal(signal){if(signal?.aborted)throw new DOMException("Cancelled","AbortError")}
async function cancelResponse(response){try{await response.body?.cancel()}catch{}}
async function boundedResponseBytes(response,limit,signal){
 checkAttachmentSignal(signal);
 const length=response.headers.get("content-length");
 if(length!==null&&(!/^\d+$/.test(length)||!Number.isSafeInteger(Number(length))||Number(length)>limit)){await cancelResponse(response);throw Error("size")}
 if(!response.body?.getReader)throw Error("network");
 const reader=response.body.getReader(),chunks=[];let size=0,complete=false;
 try{
  while(true){
   checkAttachmentSignal(signal);
   const {done,value}=await reader.read();checkAttachmentSignal(signal);
   if(done){complete=true;break}
   size+=value.byteLength;if(size>limit)throw Error("size");chunks.push(value);
  }
 }finally{if(!complete)await reader.cancel().catch(()=>{});reader.releaseLock()}
 const bytes=new Uint8Array(size);let offset=0;
 for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.byteLength}
 return bytes;
}
async function sha256Hex(bytes){return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),b=>b.toString(16).padStart(2,"0")).join("")}
async function decryptAttachment(ref,scope,encrypted,signal){
 const {key,iv}=validateAttachmentReference(ref),aad=attachmentAAD(ref,scope);
 checkAttachmentSignal(signal);
 if(encrypted.byteLength!==attachmentPaddedSize(ref.size)+16||await sha256Hex(encrypted)!==ref.path.slice(12,-4))throw Error("integrity");
 checkAttachmentSignal(signal);
 const material=await crypto.subtle.importKey("raw",key,"AES-GCM",false,["decrypt"]);
 checkAttachmentSignal(signal);
 const padded=new Uint8Array(await crypto.subtle.decrypt({name:"AES-GCM",iv,additionalData:aad},material,encrypted));
 if(padded.byteLength!==attachmentPaddedSize(ref.size))throw Error("integrity");
 const bytes=padded.slice(0,ref.size);
 checkAttachmentSignal(signal);
 if(bytes.byteLength!==ref.size||await sha256Hex(bytes)!==ref.sha256)throw Error("integrity");
 checkAttachmentSignal(signal);return bytes;
}
async function fetchAttachment(ref,scope,signal){
 const url=attachmentURL(ref);attachmentAAD(ref,scope);checkAttachmentSignal(signal);
 const response=await fetch(url.href,{cache:"no-store",credentials:"omit",referrerPolicy:"no-referrer",redirect:"error",mode:"same-origin",signal});
 if(response.status!==200||response.redirected||response.url!==url.href){await cancelResponse(response);throw Error("network")};
 return decryptAttachment(ref,scope,await boundedResponseBytes(response,attachmentPaddedSize(ref.size)+16,signal),signal);
}
function attachmentDownload(bytes,file){
 const url=URL.createObjectURL(new Blob([bytes],{type:"application/octet-stream"}));attachmentUrls.add(url);
 const link=el("a","attachment","Pobierz · "+file.name+" ("+Math.ceil(bytes.byteLength/1024)+" KB)");
 link.href=url;link.download=(file.name||"zalacznik").replace(/[\/\\\u0000-\u001f]/g,"_");return link;
}
function attachment(f,message,index){
 if(f.encrypted_attachment){
  const box=el("div","attachment-download"),status=el("span","annotation"),report=data;
  status.setAttribute("role","status");let controller=null;
  const cancel=button("Anuluj",()=>controller?.abort(),"quiet");cancel.hidden=true;
  const open=button("Pobierz · "+f.name+" ("+Math.ceil(f.encrypted_attachment.size/1024)+" KB)",async()=>{
   if(controller)return;
   const generation=attachmentGeneration;controller=new AbortController();const request=controller;
   attachmentRequests.add(request);open.disabled=true;cancel.hidden=false;status.textContent="Pobieram załącznik…";
   const timeout=setTimeout(()=>request.abort(),30000);
   try{
    if(data!==report)throw Error("scope");
    const scope=attachmentContext(report,message,index,f),bytes=await fetchAttachment(f.encrypted_attachment,scope,request.signal);
    checkAttachmentSignal(request.signal);
    if(data!==report||attachmentGeneration!==generation)return;
    const link=attachmentDownload(bytes,f);box.replaceChildren(link);link.click();
   }catch(error){
    if(data===report&&attachmentGeneration===generation){status.textContent=error.name==="AbortError"?"Pobieranie anulowane. Możesz spróbować ponownie.":"Nie udało się pobrać załącznika. Spróbuj ponownie.";open.textContent="Spróbuj ponownie · "+f.name}
   }finally{clearTimeout(timeout);attachmentRequests.delete(request);controller=null;open.disabled=false;cancel.hidden=true}
  },"attachment");
  box.append(open,cancel,status);return box;
 }
 if(typeof f.base64!=="string"){const p=el("div","notice");p.append(el("p","","Załącznik niedostępny: "+f.name));if(f.url)p.append(safeLink(f.url,"Sprawdź w Librusie ↗"));return p}
 try{
  if(typeof f.base64!=="string"||f.base64.length>4*Math.ceil(MAX_ATTACHMENT_BYTES/3))throw Error("size");
  const bytes=Uint8Array.from(atob(f.base64),c=>c.charCodeAt(0));if(bytes.length>MAX_ATTACHMENT_BYTES)throw Error("size");
  return attachmentDownload(bytes,f);
 }catch{return empty("Załącznik niedostępny: "+f.name)}
}
function doc(m){
 const d=el("details","document");d.dataset.id=m.id;const s=el("summary"),meta=el("div","row-meta");
 meta.append(childTag(m.child),priorityPill(m));if(isNew(m))meta.append(pill("Nowe","new"));meta.append(el("span","doc-date",shortDate(m.date)));
 s.append(meta,el("h3","doc-title",m.title),el("p","doc-preview",m.text.replace(/\s+/g," ").slice(0,180)));
 const body=el("div","doc-content");body.append(el("p","doc-author",m.sender),richText(m.text||"Brak treści."));(m.attachments||[]).forEach((f,index)=>body.append(attachment(f,m,index)));body.append(safeLink(m.url,"Oryginał w Librusie ↗"));
 const controls=el("div","document-controls");controls.append(button(isNew(m)?"Oznacz jako przeczytane":"Przeczytane",()=>markRead(m),"quiet"));
 const lbl=el("label","annotation","Priorytet "),sel=el("select");sel.setAttribute("aria-label","Priorytet wiadomości");
 Object.entries(priorityLabel).forEach(([value,title])=>{const option=el("option","",title);option.value=value;sel.append(option)});sel.value=priority(m);
 sel.addEventListener("change",()=>{reviewState.priority[m.revision]=sel.value;saveReview();render()});lbl.append(sel);controls.append(lbl);body.append(controls);d.append(s,body);return d;
}

function documents(){
 const docs=chosen().flatMap(a=>a[current]||[]).sort((a,b)=>b.date.localeCompare(a.date)),p=panel(current==="messages"?"Szkolna poczta":"Tablica ogłoszeń",docs.length+" wpisów");
 const label=el("label","search-label","Szukaj w temacie lub treści");label.htmlFor="search";const input=el("input","search");input.id="search";input.type="search";input.placeholder="Szukaj wiadomości…";input.value=query;
 const filters=el("div","attention-bar");[["all","Wszystkie"],["new","Nowe"],["urgent","Pilne"]].forEach(([id,title])=>{const b=button(title,()=>{documentFilter=id;render()},"attention-button");b.setAttribute("aria-pressed",String(id===documentFilter));filters.append(b)});
 const list=el("div");const refreshList=()=>{releaseAttachments();const q=input.value.trim().toLocaleLowerCase("pl");query=input.value;const filtered=docs.filter(m=>(m.title+" "+m.text+" "+m.sender).toLocaleLowerCase("pl").includes(q)).filter(m=>documentFilter==="all"||documentFilter==="new"&&isNew(m)||documentFilter==="urgent"&&priority(m)==="urgent");list.replaceChildren(...filtered.map(doc));if(!filtered.length)list.append(empty("Nie znaleziono pasujących wpisów."))};
 input.addEventListener("input",refreshList);refreshList();p.append(label,input,filters,list);$("main").append(p);
}

function timetable(){
 const accounts=chosen(),p=panel("Cały tydzień","Godziny lekcji"),matrix=el("div","week-matrix"+(accounts.length===1?" single":"")),head=el("div","week-heading");head.append(el("span","","Dzień"));accounts.forEach(a=>head.append(el("strong","",a.name)));matrix.append(head);
 const dateKeys=[...new Set(accounts.flatMap(a=>(a.sections?.timetable?.days||[]).map(d=>d.label.match(/\d{4}-\d{2}-\d{2}/)?.[0]).filter(Boolean)))].sort();
 if(!dateKeys.length)p.append(empty("Brak odczytanego planu."));
 const shortDays={"poniedziałek":"Pon.","wtorek":"Wt.","środa":"Śr.","czwartek":"Czw.","piątek":"Pt.","sobota":"Sob.","niedziela":"Niedz."};
 dateKeys.forEach(date=>{
  const line=el("div","week-line"),dayLabel=el("div","week-label");const weekday=datePL(date,{weekday:"long"});dayLabel.append(el("strong","",shortDays[weekday]||weekday),el("small","",datePL(date,{day:"numeric",month:"2-digit"})));line.append(dayLabel);
  const details=el("div","week-details");details.hidden=true;line.append(details);
  accounts.forEach(a=>{
   const day=a.sections?.timetable?.days?.find(d=>d.label.includes(date)),plan=lessonSpan(day),active=plan.active,trip=(a.sections?.attendance?.entries||[]).some(e=>e.date===date&&e.details?.includes("Czy wycieczka: Tak")),span=trip?"Wycieczka":day?plan.span:"Brak odczytu";
   const b=el("button","week-slot");b.type="button";
   b.setAttribute("aria-label",a.name+", "+weekday+", "+span+". Rozwiń lekcje");b.setAttribute("aria-expanded","false");b.append(el("strong","",span),el("span","",trip?"sprawdź godziny":!day?"brak odczytu":active.length?lessonCount(active.length)+" ↗":day.lessons.length?"odwołane · szczegóły":"brak wpisów"));
   b.addEventListener("click",()=>{
    const close=b.getAttribute("aria-expanded")==="true";line.querySelectorAll("button").forEach(x=>x.setAttribute("aria-expanded","false"));details.replaceChildren();details.hidden=close;if(close)return;b.setAttribute("aria-expanded","true");details.append(el("h3","",a.name+" · "+weekday));if(trip)details.append(el("p","notice","Frekwencja wskazuje wycieczkę. Godziny wyjścia i powrotu nie są podane w planie lekcji."));
    if(!day?.lessons?.length)details.append(empty("W odczytanym planie nie ma lekcji na ten dzień."));
    (day?.lessons||[]).forEach(lesson=>{const row=el("div","lesson");row.append(el("time","",lesson.time.replace(/\s*-\s*/,"–")));const body=el("div"),canceled=lesson.text.toLowerCase().includes("odwołane");body.append(el("span",canceled?"canceled":"",lesson.text));if(canceled)body.append(el("small","","Lekcja odwołana"));if(lesson.details?.length)body.append(el("small","",lesson.details.join("\n")));row.append(body);details.append(row)});
   });
   line.insertBefore(b,details);
  });matrix.append(line);
 });
 p.append(matrix);const sources=el("div","schedule-sources");accounts.forEach(a=>{if(a.sections?.timetable)sources.append(safeLink(a.sections.timetable.url,a.name+" · Librus ↗"))});p.append(sources,el("p","week-footnote","Godziny bez dojazdów. Odwołanie lekcji nie wyklucza wycieczki; sprawdź też frekwencję."));$("main").append(p);
}

function dates(){
 const actions=allActions().filter(a=>a.date).sort((a,b)=>a.date.localeCompare(b.date));
 if(actions.length){const p=panel("Z wiadomości i ustaleń");actions.forEach(a=>p.append(actionRow(a)));$("main").append(p)}
 const p=panel("Terminarz Librusa","Pełny odczyt dostępnego miesiąca");chosen().forEach(a=>{
 const sec=a.sections?.dates;const wrap=el("section","child-section");wrap.append(el("h3","child-title",a.name));if(!sec?.events?.length)wrap.append(empty("Brak wpisów w odczytanym terminarzu."));
 [...(sec?.events||[])].sort((a,b)=>a.date.localeCompare(b.date)).forEach(e=>{const row=el("article","timeline-row");row.append(pill(datePL(e.date)),el("h3","",e.text),el("p","",e.details));wrap.append(row)});
 if(sec){wrap.append(sectionReview(sec));wrap.append(safeLink(sec.url,"Terminarz w Librusie ↗"));}p.append(wrap)
 });$("main").append(p);
}
function grades(){
 const p=panel("Oceny według przedmiotów","Rozwiń ocenę, aby poznać szczegóły");
 chosen().forEach(a=>{
 const sec=a.sections?.grades;const wrap=el("section","child-section");wrap.append(el("h3","child-title",a.name));if(!sec){wrap.append(empty("Nie udało się odczytać ocen."));p.append(wrap);return}
 if(!(sec.subjects||[]).some(s=>s.grades.length))wrap.append(empty("W Librusie nie ma jeszcze ocen bieżących."));
 const table=el("table"),thead=el("thead"),tr=el("tr");["Przedmiot","Okres 1","Okres 2","Roczna"].forEach(s=>tr.append(el("th","",s)));thead.append(tr);table.append(thead);const body=el("tbody");
 (sec.subjects||[]).forEach(s=>{const row=el("tr");row.append(el("td","",s.subject));[1,2].forEach(term=>{const td=el("td"),grades=s.grades.filter(g=>g.term===term);if(!grades.length)td.append(el("span","muted","Brak ocen"));grades.forEach(g=>{const d=el("details","grade");d.append(el("summary","",g.value),el("p","",g.details||"Brak dodatkowego opisu."));td.append(d)});const final=term===1?s.final1:s.final2;if(final&&final!=="-")td.append(el("p","annotation","Śródroczna: "+final));row.append(td)});row.append(el("td","",s.year==="-"?"—":s.year));body.append(row)});
 table.append(body);const scroll=el("div","table-wrap");scroll.append(table);if(!(sec.subjects||[]).some(s=>s.grades.length||[s.final1,s.final2,s.year].some(x=>x&&x!=="-"))){const catalog=el("details","subject-catalog");catalog.append(el("summary","","Lista przedmiotów · "+(sec.subjects||[]).length),scroll);wrap.append(catalog)}else wrap.append(scroll);
 if(sec.descriptive?.length){const h=el("h3","child-title","Oceny opisowe");h.classList.add("source-raw");wrap.append(h);sec.descriptive.forEach(d=>{const row=el("article","timeline-row");row.append(el("h4","",d.area),el("p","muted",d.text.trim()||"Brak wpisów."));if(d.details.length)row.append(el("p","",d.details.join("\n")));wrap.append(row)})}
 wrap.append(sectionReview(sec),raw(sec));p.append(wrap);
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
 wrap.append(sectionReview(sec),raw(sec));p.append(wrap)
 });$("main").append(p);
}
function simple(){
 const p=panel(current==="notes"?"Uwagi ze szkoły":"Osiągnięcia w dzienniku");chosen().forEach(a=>{const sec=a.sections?.[current],wrap=el("section","child-section");wrap.append(el("h3","child-title",a.name));if(!sec)wrap.append(empty("Brak odczytu tej sekcji."));else if(sec.empty)wrap.append(empty(current==="notes"?"Brak uwag w Librusie.":"Brak szczególnych osiągnięć wpisanych w Librusie."));else wrap.append(el("div","raw-text",sec.text));if(sec)wrap.append(sectionReview(sec),safeLink(sec.url,"Otwórz w Librusie ↗"));p.append(wrap)});$("main").append(p);
}
function homework(){
 const p=panel("Zadania i przygotowania");chosen().forEach(a=>{
 const sec=a.sections?.homework,wrap=el("section","child-section");wrap.append(el("h3","child-title",a.name));
 const events=(a.sections?.dates?.events||[]).filter(e=>/praca domowa|zadani|lektur/i.test(e.text+" "+e.details));
 events.forEach(e=>{const row=el("article","timeline-row");row.append(pill("Terminarz"),pill(datePL(e.date),"violet"),el("h3","",e.text),el("p","",e.details));wrap.append(row)});
 if(sec){if(/Brak wpisów/i.test(sec.text))wrap.append(empty("Moduł „Zadania domowe” nie zawiera wpisów."));else wrap.append(el("div","raw-text",sec.text));wrap.append(sectionReview(sec),safeLink(sec.url,"Zadania w Librusie ↗"))}else wrap.append(empty("Brak odczytu modułu zadań."));p.append(wrap)
 });$("main").append(p);
}
function fromB64(s){return Uint8Array.from(atob(s),c=>c.charCodeAt(0))}
async function fetchReport(signal){
 const request=new AbortController(),cancel=()=>request.abort();
 if(signal?.aborted)request.abort();else signal?.addEventListener("abort",cancel,{once:true});
 reportRequests.add(request);const timeout=setTimeout(cancel,30000);
 try{
  for(const path of ["report.v2.enc.json","report.enc.json"]){
   checkAttachmentSignal(request.signal);
   const url=new URL(path,REPORT_SITE_ROOT);url.searchParams.set("t",String(Date.now()));
   const response=await fetch(url.href,{cache:"no-store",credentials:"omit",referrerPolicy:"no-referrer",redirect:"error",mode:"same-origin",signal:request.signal});
   checkAttachmentSignal(request.signal);
   if(response.redirected||response.url!==url.href){await cancelResponse(response);throw Error("network")}
   if(response.status===404&&path==="report.v2.enc.json"){await cancelResponse(response);continue}
   if(response.status!==200){await cancelResponse(response);throw Error("network")}
   const bytes=await boundedResponseBytes(response,MAX_REPORT_BYTES,request.signal);
   checkAttachmentSignal(request.signal);
   const envelope=JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes));
   if(envelope.v!==1||envelope.iterations!==600000)throw Error("format");
   reportEnvelopeSchemas.set(envelope,path==="report.v2.enc.json"?2:1);return envelope;
  }
  throw Error("network");
 }finally{clearTimeout(timeout);signal?.removeEventListener("abort",cancel);reportRequests.delete(request);request.abort()}
}
async function decrypt(envelope,material){
 if(envelope.v!==1||envelope.iterations!==600000)throw Error("format");
 const salt=strictAttachmentBase64(envelope.salt,16),iv=strictAttachmentBase64(envelope.iv,12);
 if(typeof envelope.ciphertext!=="string"||envelope.ciphertext.length>MAX_REPORT_BYTES)throw Error("format");
 const key=await crypto.subtle.deriveKey({name:"PBKDF2",salt,iterations:envelope.iterations,hash:"SHA-256"},material,{name:"AES-GCM",length:256},false,["decrypt"]);
 const plain=await crypto.subtle.decrypt({name:"AES-GCM",iv,additionalData:new TextEncoder().encode("promenada-report-v1")},key,fromB64(envelope.ciphertext));
 const report=validateReportAccess(JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(plain)),{audience:"parent",principal:"parent"});
 const expectedSchema=reportEnvelopeSchemas.get(envelope);
 if(expectedSchema!==undefined&&report.schema!==expectedSchema)throw Error("format");
 return report;
}
$("unlock-form").addEventListener("submit",async e=>{
 e.preventDefault();const generation=++sessionGeneration;cancelReportRequests();$("unlock").disabled=true;$("gate-status").textContent="Otwieram dziennik…";
 try{
 const password=$("password").value.trim();if(!password)throw Error("empty");
 const material=await crypto.subtle.importKey("raw",new TextEncoder().encode(password),"PBKDF2",false,["deriveKey"]);
 if(generation!==sessionGeneration)return;
 let envelope;try{envelope=await fetchReport()}catch{throw Error("network")}
 const report=await decrypt(envelope,material);if(generation!==sessionGeneration)return;data=report;keyMaterial=material;$("password").value="";$("gate-status").textContent="";$("gate").hidden=true;$("journal").hidden=false;$("lock").hidden=false;activity=Date.now();render();$("main").focus({preventScroll:true});
 }catch(e){if(generation===sessionGeneration)$("gate-status").textContent=e.message==="network"?"Nie udało się pobrać raportu. Sprawdź połączenie i spróbuj ponownie.":"Hasło nie otwiera dziennika. Sprawdź je i spróbuj ponownie."}
 finally{$("unlock").disabled=false}
});
$("show-password").addEventListener("change",e=>{$("password").type=e.target.checked?"text":"password"});
function lock(){sessionGeneration++;cancelReportRequests();releaseAttachments();data=null;keyMaterial=null;selected=null;current="overview";query="";$("main").replaceChildren();$("children").replaceChildren();$("nav").replaceChildren();$("health").replaceChildren();$("updated").textContent="";$("sync-status").textContent="";$("journal").hidden=true;$("gate").hidden=false;$("lock").hidden=true;$("password").type="password";$("show-password").checked=false;$("password").value="";window.scrollTo({top:0,behavior:"instant"})}
$("lock").addEventListener("click",lock);
$("refresh").addEventListener("click",async()=>{
 if(!keyMaterial)return;const material=keyMaterial;const before=data?.collected_at;
 $("refresh").disabled=true;$("refresh").textContent="Sprawdzam…";$("sync-status").textContent="";
 try{
  const fresh=await decrypt(await fetchReport(),material);
  if(keyMaterial!==material)return;
  data=fresh;render();
  $("sync-status").textContent=fresh.collected_at===before?"Masz najnowszy opublikowany raport. Ten przycisk sprawdza gotowe raporty; odczyt Librusa odbywa się rano i wieczorem.":"Wczytano raport z "+datePL(fresh.collected_at,{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"})+".";
 }catch{if(keyMaterial===material)$("sync-status").textContent="Nie udało się pobrać raportu. Oglądasz ostatnio otwartą wersję."}
 finally{$("refresh").disabled=false;$("refresh").textContent="Sprawdź raport"}
});
["pointerdown","keydown"].forEach(type=>document.addEventListener(type,()=>activity=Date.now(),{passive:true}));
setInterval(()=>{if(data&&Date.now()-activity>30*60*1000)lock()},60000);
window.addEventListener("pagehide",lock);
