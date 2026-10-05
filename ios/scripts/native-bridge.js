
const nativeSend = (action, extra={}) => window.webkit.messageHandlers.journal.postMessage({action,...extra});
saveReview = () => nativeSend("review",{value:JSON.stringify(reviewState)});
attachment = (f,message,index) => {
 if(f.encrypted_attachment){
  return button("Otwórz · "+f.name+" ("+Math.ceil(f.encrypted_attachment.size/1024)+" KB)",()=>{
   try{
    const context=attachmentContext(data,message,index,f);validateAttachmentReference(f.encrypted_attachment);
    nativeSend("attachment",{name:f.name||"zalacznik",accountKey:context.accountKey,source:context.source,messageId:context.messageId,attachmentIndex:context.attachmentIndex,ref:f.encrypted_attachment,scope:{audience:context.audience,principal:context.principal}});
   }catch{$("sync-status").textContent="Nie udało się otworzyć załącznika. Wczytaj raport i spróbuj ponownie."}
  },"attachment");
 }
 if(typeof f.base64!=="string")return empty("Załącznik niedostępny: "+f.name);
 return button("Otwórz · "+f.name+" ("+Math.ceil(f.size/1024)+" KB)",()=>nativeSend("attachment",{name:f.name||"zalacznik",base64:f.base64}),"attachment");
};
window.promenadaReceive=(report,status,saved,automatic=false)=>{
 validateReportAccess(report);
 const before=data?.collected_at;
 // Re-encryption can replace attachment references without changing collection time.
 // Keep the old DOM only when the entire validated manifest is identical.
 if(automatic&&data&&before===report.collected_at&&data.schema===report.schema&&JSON.stringify(data)===JSON.stringify(report)){
  renderHealth();
  $("sync-status").textContent=status||"";
  return;
 }
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
