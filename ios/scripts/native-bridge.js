
const nativeSend = (action, extra={}) => window.webkit.messageHandlers.journal.postMessage({action,...extra});
saveReview = () => nativeSend("review",{value:JSON.stringify(reviewState)});
attachment = f => {
 if(!f.base64)return empty("Załącznik niedostępny: "+f.name);
 return button("Otwórz · "+f.name+" ("+Math.ceil(f.size/1024)+" KB)",()=>nativeSend("attachment",{name:f.name||"zalacznik",base64:f.base64}),"attachment");
};
window.promenadaReceive=(report,status,saved)=>{
 const before=data?.collected_at;
 data=report;
 if(saved)reviewState=saved;
 $("gate").hidden=true;$("journal").hidden=false;$("lock").hidden=false;
 $("lock").textContent="Wyloguj";
 render();
 $("refresh").disabled=false;$("refresh").textContent="Odśwież z Librusa";
 $("sync-status").textContent=status||(before?(before===data.collected_at?"Masz najnowszy opublikowany raport.":"Wczytano nowszy raport."):"");
};
window.promenadaClear=()=>{
 releaseAttachments();data=null;reviewState={read:{},done:{},priority:{}};selected="all";current="overview";query="";
 $("main").replaceChildren();$("journal").hidden=true;
};
$("lock").addEventListener("click",()=>nativeSend("forget"));
$("refresh").addEventListener("click",()=>{
 $("refresh").disabled=true;$("refresh").textContent="Sprawdzam…";nativeSend("refresh");
});
document.querySelector(".wordmark").removeAttribute("href");
const published=button("Wczytaj raport",()=>nativeSend("published"),"quiet");
published.id="published-refresh";
$("refresh").after(published);
nativeSend("ready");
