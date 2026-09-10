"use strict";
const attachmentUrls=new Set();
function releaseAttachments(){for(const url of attachmentUrls)URL.revokeObjectURL(url);attachmentUrls.clear()}
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
 [["all","Do przejrzenia"],["urgent","Pilne"],["todo","Do dopilnowania"],["new","Nowe"],["done","Zrobione"]].forEach(([id,title])=>{const b=button(title,()=>{attentionFilter=id;render()},"attention-button");b.setAttribute("aria-pressed",String(attentionFilter===id));bar.append(b)});
 return bar;
}
function sectionReview(sec){const box=el("div","section-review");if(isNew(sec)){box.append(pill("Nowe dane","new"),button("Oznacz jako przejrzane",()=>markRead(sec),"text-button"))}else box.append(el("span","annotation","Przejrzane na tym urządzeniu"));return box}

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
function navigate(id){current=id;query="";attentionFilter="all";render();$("main").focus({preventScroll:true});window.scrollTo({top:0,behavior:"instant"})}
function getDocuments(){return Object.values(data.accounts).flatMap(a=>[...(a.messages||[]),...(a.announcements||[])])}
function openSource(id,fallback){const m=getDocuments().find(m=>m.id===id);if(m){current=m.kind==="announcement"?"announcements":"messages";selected=m.child;query="";render();const d=Array.from(document.querySelectorAll(".document")).find(x=>x.dataset.id===id);if(d){d.open=true;d.scrollIntoView({block:"start",behavior:"smooth"})}}else navigate(fallback||"dates")}
function missedCollection(){
 const parts=d=>Object.fromEntries(new Intl.DateTimeFormat("sv-SE",{timeZone:"Europe/Warsaw",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).formatToParts(d).filter(p=>p.type!=="literal").map(p=>[p.type,p.value]));
 const now=parts(new Date()),read=parts(new Date(data.collected_at)),today=now.year+"-"+now.month+"-"+now.day,readAt=read.year+"-"+read.month+"-"+read.day+"T"+read.hour+":"+read.minute;
 const hour=+now.hour;
 const target=hour>=19?"18:00":hour>=8?"07:00":null;
 return target?readAt<today+"T"+target:Date.now()-new Date(data.collected_at).getTime()>15*3600000;
}
function render(){
 if(!data)return;
 releaseAttachments();
 $("children").replaceChildren();
 [["all","Oboje"],...Object.values(data.accounts).map(a=>[a.child,a.name])].forEach(([id,label])=>{const b=button(label,()=>{selected=id;query="";render()});b.setAttribute("aria-pressed",String(selected===id));$("children").append(b)});
 $("updated").textContent="Odczyt: "+datePL(data.collected_at,{day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"});
 $("health").replaceChildren();
 const bad=Object.values(data.accounts).filter(a=>a.status!=="ok");
 if(bad.length){const n=el("div","notice");n.append(el("p","","Nie udało się odświeżyć konta: "+bad.map(a=>a.name).join(", ")+". Poniżej ostatni poprawny odczyt."));$("health").append(n)}
 if(missedCollection()){$("health").append(el("div","notice","Brakuje raportu z ostatniej pory odczytu. Serwer może jeszcze ponawiać zadanie. Widoczna data pokazuje rzeczywisty odczyt — przycisk sprawdzi, czy pojawił się nowszy plik."))}
 $("nav").replaceChildren();
 sections.forEach(([id,label],i)=>{const b=button("",()=>navigate(id));b.append(el("span","",String(i+1).padStart(2,"0")),el("span","",label));const n=newCount(id);if(n)b.append(el("span","nav-count",String(n)));if(id===current)b.setAttribute("aria-current","page");$("nav").append(b)});
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
 const body=el("div");body.append(pill(name(a.child)),priorityPill(a));if(a.date&&a.date<dayISO()&&!isDone(a))body.append(pill("Po terminie","priority-urgent"));if(isNew(a)&&!isDone(a))body.append(pill("Nowe","new"));body.append(el("h3","",a.title),el("p","",a.text));
 if(a.source_id)body.append(button("Przeczytaj źródło ↗",()=>openSource(a.source_id,a.section),"text-button"));
 else if(a.section)body.append(button("Zobacz szczegóły ↗",()=>navigate(a.section),"text-button"));
 if(a.id)body.append(button(isDone(a)?"Zrobione · cofnij":"Oznacz jako zrobione",()=>toggleDone(a),"task-check"));if(isDone(a))row.classList.add("completed");row.append(date,body);return row;
}
function overview(){
 const p=panel("Na najbliższe dni","Z wiadomości i terminarza");p.append(attentionBar());
 const ranks={urgent:0,todo:1,info:2};const actions=allActions().filter(a=>attentionFilter==="done"?isDone(a):!isDone(a)).filter(a=>attentionFilter==="all"||attentionFilter==="done"||attentionFilter==="new"&&isNew(a)||priority(a)===attentionFilter).sort((a,b)=>ranks[priority(a)]-ranks[priority(b)]||(a.date||"9999").localeCompare(b.date||"9999"));
 if(actions.length)actions.forEach(a=>p.append(actionRow(a)));else p.append(empty("Nie ma spraw pasujących do tego filtra."));p.append(el("p","annotation review-note","Znaczniki nowych, przeczytanych i zrobionych spraw zapisują się na tym urządzeniu."));
 $("main").append(p);
 const fresh=chosen().flatMap(a=>[...(a.messages||[]),...(a.announcements||[])]).filter(isNew).sort((a,b)=>b.date.localeCompare(a.date));if(fresh.length){const inbox=panel("Nowe dla Ciebie",fresh.length+" do przeczytania");fresh.slice(0,5).forEach(m=>{const row=el("article","timeline-row");row.append(pill(name(m.child)),priorityPill(m),el("h3","",m.title),el("p","muted",m.text.slice(0,220)+(m.text.length>220?"…":"")),button("Otwórz i przeczytaj ↗",()=>openSource(m.id),"text-button"));inbox.append(row)});$("main").append(inbox)}
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
 const bytes=Uint8Array.from(atob(f.base64),c=>c.charCodeAt(0));
 const url=URL.createObjectURL(new Blob([bytes],{type:"application/octet-stream"}));
 attachmentUrls.add(url);
 const a=el("a","attachment","Pobierz · "+f.name+" ("+Math.ceil(f.size/1024)+" KB)");
 a.href=url;a.download=(f.name||"zalacznik").replace(/[\/\\\u0000-\u001f]/g,"_");
 return a;
}
function doc(m){
 const d=el("details","document");d.dataset.id=m.id;const s=el("summary");
 s.append(pill(name(m.child)),priorityPill(m));if(isNew(m))s.append(pill("Nowe","new"));s.append(el("span","doc-meta",datePL(m.date)),el("h3","doc-title",m.title),el("p","doc-meta",m.sender));
 const body=el("div","doc-content");body.append(richText(m.text||"Brak treści."));(m.attachments||[]).forEach(f=>body.append(attachment(f)));body.append(safeLink(m.url,"Oryginał w Librusie ↗"));const controls=el("div","document-controls");controls.append(button(isNew(m)?"Oznacz jako przeczytane":"Przeczytane",()=>markRead(m),"quiet"));const lbl=el("label","annotation","Priorytet ");const sel=el("select");sel.setAttribute("aria-label","Priorytet wiadomości");Object.entries(priorityLabel).forEach(([value,title])=>{const option=el("option","",title);option.value=value;sel.append(option)});sel.value=priority(m);sel.addEventListener("change",()=>{reviewState.priority[m.revision]=sel.value;saveReview();render()});lbl.append(sel);controls.append(lbl);body.append(controls);d.append(s,body);return d;
}
function documents(){
 const docs=chosen().flatMap(a=>a[current]||[]).sort((a,b)=>b.date.localeCompare(a.date));
 const p=panel(current==="messages"?"Połączona skrzynka":"Tablica ogłoszeń","Liczba wpisów: "+docs.length), label=el("label","search-label","Szukaj w temacie, treści lub autorze");label.htmlFor="search";
 const input=el("input","search");input.id="search";input.type="search";input.placeholder="Wpisz słowo lub nazwisko";input.value=query;
 const list=el("div");const refreshList=()=>{releaseAttachments();const q=input.value.trim().toLocaleLowerCase("pl");query=input.value;const filtered=docs.filter(m=>(m.title+" "+m.text+" "+m.sender).toLocaleLowerCase("pl").includes(q));list.replaceChildren(...filtered.map(doc));if(!filtered.length)list.append(empty("Nie znaleziono pasujących wpisów."))};
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
 child.append(sectionReview(sec),safeLink(sec.url,"Plan w Librusie ↗"));p.append(child);
 });
 p.append(el("p","annotation","Odwołana lekcja nie przesądza o pobycie w domu. Wycieczki i zwolnienia sprawdzisz w frekwencji."));$("main").append(p);
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
 table.append(body);const scroll=el("div","table-wrap");scroll.append(table);wrap.append(scroll);
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
function lock(){releaseAttachments();data=null;keyMaterial=null;selected="all";current="overview";query="";$("main").replaceChildren();$("children").replaceChildren();$("nav").replaceChildren();$("health").replaceChildren();$("updated").textContent="";$("sync-status").textContent="";$("journal").hidden=true;$("gate").hidden=false;$("lock").hidden=true;$("password").type="password";$("show-password").checked=false;$("password").value="";window.scrollTo({top:0,behavior:"instant"})}
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
