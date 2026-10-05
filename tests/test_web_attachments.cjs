// Synthetic-only reader tests. No request is ever sent to a live site.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {webcrypto} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const app = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
const bridge = fs.readFileSync(path.join(root, 'ios/scripts/native-bridge.js'), 'utf8');
function element(tag) {
 return {tag, children:[], listeners:{}, dataset:{}, append(...values){this.children.push(...values)}, replaceChildren(...values){this.children=values}, setAttribute(){}, removeAttribute(){}, after(){}, addEventListener(type,handler){this.listeners[type]=handler}, click(){this.clicked=true;return this.listeners.click?.()}, focus(){}};
}
function load() {
 const elements = new Map(), nativeMessages = [], requests = [];
 const context = {console,crypto:webcrypto,atob,btoa,TextEncoder,TextDecoder,URL,Blob,Uint8Array,AbortController,DOMException,setTimeout,clearTimeout,
  localStorage:{getItem(){return null}},
  document:{createElement:element,getElementById(id){if(!elements.has(id))elements.set(id,element('div'));return elements.get(id)},querySelector(){return element('a')}},
  window:{webkit:{messageHandlers:{journal:{postMessage(value){nativeMessages.push(value)}}}}},
  fetch:async (url,options)=>{requests.push([url,options]);throw Error('Live fetch forbidden')}
 };
 vm.createContext(context);
 vm.runInContext(app.slice(0,app.indexOf('$("unlock-form").addEventListener'))+`
 globalThis.helpers={attachmentAAD,attachmentContext,validateReportAccess,validateAttachmentReference,attachmentPaddedSize,attachmentURL,boundedResponseBytes,decryptAttachment,fetchAttachment,fetchReport,decrypt,attachment,releaseAttachments,cancelReportRequests};
 globalThis.setReport=report=>{data=report};
 globalThis.getData=()=>data;
 globalThis.attachmentURLs=attachmentUrls;
 `,context);
 return {context,h:context.helpers,elements,nativeMessages,requests};
}
function response(url,bytes,{status=200,redirected=false,declared=bytes.length,chunkSize=8192}={}) {
 let offset=0,cancelled=false;
 return {url,status,redirected,headers:{get(name){return name==='content-length'&&declared!==null?String(declared):null}},
 body:{cancel(){cancelled=true;return Promise.resolve()},getReader(){return {async read(){if(offset>=bytes.length)return {done:true};const value=bytes.slice(offset,offset+chunkSize);offset+=value.length;return {done:false,value}},async cancel(){cancelled=true},releaseLock(){}}}},
 get cancelled(){return cancelled}};
}
async function makeFixture(h,changes={}) {
 const bytes=Buffer.from('Original bytes: \0\xff\nZażółć gęślą 👩‍🚀','utf8');
 const scope={audience:'parent',principal:'parent',accountKey:'dziecko/"\\\u2028\u2029',source:'messages',messageId:'dziecko/"\\\u2028\u2029:message:mail/"\\\u2028\u2029',attachmentIndex:0,...changes};
 const key=webcrypto.getRandomValues(new Uint8Array(32)),iv=webcrypto.getRandomValues(new Uint8Array(12));
 const hash=async bytes=>Buffer.from(await webcrypto.subtle.digest('SHA-256',bytes)).toString('hex');
 const ref={v:1,path:'attachments/'+ '0'.repeat(64)+'.bin',key:Buffer.from(key).toString('base64'),iv:Buffer.from(iv).toString('base64'),sha256:await hash(bytes),size:bytes.length};
 const material=await webcrypto.subtle.importKey('raw',key,'AES-GCM',false,['encrypt']);
 const padded=new Uint8Array(h.attachmentPaddedSize(bytes.length));padded.set(bytes);
 const ciphertext=new Uint8Array(await webcrypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:h.attachmentAAD(ref,scope)},material,padded));
 ref.path='attachments/'+await hash(ciphertext)+'.bin';
 const file={name:'oryginał z załącznikiem.bin',mime:'application/octet-stream',size:bytes.length,encrypted_attachment:ref};
 const message={id:scope.messageId,child:scope.accountKey,kind:'message',attachments:[file]};
 const report={schema:2,...(scope.audience==='student'?{audience:scope.audience,principal:scope.principal}:{}),accounts:{[scope.accountKey]:{child:scope.accountKey,role:scope.audience,messages:[message],announcements:[]}}};
 return {bytes,scope,ref,ciphertext,file,message,report,hash,padded};
}

test('schema 1 and 2 work; audience, principal and child boundaries fail closed',async()=>{
 const {h}=load();const f=await makeFixture(h);
 for(const schema of [1,2])assert.equal(h.validateReportAccess({...f.report,schema},{audience:'parent',principal:'parent'}).schema,schema);
 assert.throws(()=>h.validateReportAccess({...f.report,schema:3}));
 assert.throws(()=>h.validateReportAccess({...f.report,audience:'student',principal:'a'.repeat(64)},{audience:'parent',principal:'parent'}));
 assert.throws(()=>h.validateReportAccess({...f.report,principal:'another-parent'}));
 for(const field of ['audience','principal'])for(const value of ['',null,false])assert.throws(()=>h.validateReportAccess({...f.report,[field]:value}));
 assert.throws(()=>h.validateReportAccess({...f.report,accounts:{}}));
 for(const role of ['student','other',null])assert.throws(()=>h.validateReportAccess({...f.report,accounts:{[f.scope.accountKey]:{...f.report.accounts[f.scope.accountKey],role}}}));
 const student={...f.report,audience:'student',principal:'a'.repeat(64),accounts:{[f.scope.accountKey]:{...f.report.accounts[f.scope.accountKey],role:'student'}},digest:{actions:[]}};
 assert.equal(h.validateReportAccess(student,{audience:'student',principal:'a'.repeat(64)}).schema,2);
 assert.throws(()=>h.validateReportAccess(student,{audience:'student',principal:'b'.repeat(64)}));
 assert.throws(()=>h.validateReportAccess({...student,digest:{actions:[{child:'sibling'}]}}));
 assert.throws(()=>h.validateReportAccess({...student,accounts:{...student.accounts,sibling:{role:'student'}}}));
 f.message.child='sibling';assert.throws(()=>h.validateReportAccess(f.report));
});

test('AES-GCM round trip and compact UTF-8 scoped AAD preserve original bytes',async()=>{
 const {h}=load(),f=await makeFixture(h);
 const expected=JSON.stringify(['promenada-attachment-v1','parent','parent',f.scope.accountKey,f.scope.messageId,0,f.ref.sha256,f.ref.size]);
 assert.equal(new TextDecoder().decode(h.attachmentAAD(f.ref,f.scope)),expected);
 assert.deepEqual(Buffer.from(await h.decryptAttachment(f.ref,f.scope,f.ciphertext)),f.bytes);
 const resolved=h.attachmentContext(f.report,f.message,0,f.file);assert.equal(resolved.accountKey,f.scope.accountKey);assert.equal(resolved.source,'messages');
});

test('moving a reference across any AAD scope fails authentication',async()=>{
 const {h}=load(),f=await makeFixture(h);
 for(const changes of [{accountKey:'sibling'},{messageId:'other'},{attachmentIndex:1},{source:'announcements'},{audience:'student',principal:'a'.repeat(64)},{audience:'student',principal:'b'.repeat(64)}])
  await assert.rejects(h.decryptAttachment(f.ref,{...f.scope,...changes},f.ciphertext));
 const student=await makeFixture(h,{audience:'student',principal:'a'.repeat(64)});
 await assert.rejects(h.decryptAttachment(student.ref,{...student.scope,principal:'b'.repeat(64)},student.ciphertext));
 assert.throws(()=>h.attachmentContext(f.report,{...f.message},0,f.file));
 assert.throws(()=>h.attachmentContext(f.report,f.message,1,f.file));
 f.report.accounts[f.scope.accountKey].announcements.push(f.message);assert.throws(()=>h.attachmentContext(f.report,f.message,0,f.file));
});

test('ciphertext digest, tag, plaintext digest, exact length and key tampering are rejected',async()=>{
 const {h}=load(),f=await makeFixture(h);
 const altered=f.ciphertext.slice();altered[0]^=1;
 await assert.rejects(h.decryptAttachment(f.ref,f.scope,altered));
 const refWithAlteredHash={...f.ref,path:'attachments/'+await f.hash(altered)+'.bin'};
 await assert.rejects(h.decryptAttachment(refWithAlteredHash,f.scope,altered));
 await assert.rejects(h.decryptAttachment({...f.ref,sha256:'f'.repeat(64)},f.scope,f.ciphertext));
 await assert.rejects(h.decryptAttachment({...f.ref,size:f.ref.size-1},f.scope,f.ciphertext));
 await assert.rejects(h.decryptAttachment({...f.ref,key:Buffer.alloc(32).toString('base64')},f.scope,f.ciphertext));
 await assert.rejects(h.decryptAttachment(f.ref,f.scope,f.ciphertext.slice(1)));
 // A valid GCM tag with a manifest digest deliberately different from the plaintext must still fail.
 const badDigest={...f.ref,sha256:'f'.repeat(64)};
 const material=await webcrypto.subtle.importKey('raw',Buffer.from(f.ref.key,'base64'),'AES-GCM',false,['encrypt']);
 const sealed=new Uint8Array(await webcrypto.subtle.encrypt({name:'AES-GCM',iv:Buffer.from(f.ref.iv,'base64'),additionalData:h.attachmentAAD(badDigest,f.scope)},material,f.padded));
 badDigest.path='attachments/'+await f.hash(sealed)+'.bin';await assert.rejects(h.decryptAttachment(badDigest,f.scope,sealed));
});

test('strict manifest rejects paths, URLs, noncanonical keys, wrong sizes and versions',async()=>{
 const {h}=load(),f=await makeFixture(h);
 for(const path of ['https://evil.invalid/x','//evil.invalid/x','attachments/../report.enc.json','attachments/%2e%2e/x',f.ref.path+'?x=1',f.ref.path+'#x',f.ref.path.replace('attachments/','attachments\\'),f.ref.path.toUpperCase()])assert.throws(()=>h.attachmentURL({...f.ref,path}));
 for(const size of [-1,8000001,1.5,NaN,'12',true])assert.throws(()=>h.validateAttachmentReference({...f.ref,size}));
 for(const key of ['',f.ref.key+'=',f.ref.key+'\n',f.ref.key.replace(/.$/,'_'),Buffer.alloc(31).toString('base64')])assert.throws(()=>h.validateAttachmentReference({...f.ref,key}));
 assert.throws(()=>h.validateAttachmentReference({...f.ref,iv:Buffer.alloc(13).toString('base64')}));
 assert.throws(()=>h.validateAttachmentReference({...f.ref,v:2}));
 assert.throws(()=>h.validateAttachmentReference({...f.ref,extra:'unsupported'}));
 h.validateAttachmentReference({...f.ref,size:0});h.validateAttachmentReference({...f.ref,size:8000000});
});

test('lazy attachment transport is capped, same-origin, redirect-free, and exact',async()=>{
 const {context,h}=load(),f=await makeFixture(h),url=h.attachmentURL(f.ref).href;
 let calls=0;
 context.fetch=async(request,options)=>{calls++;assert.equal(request,url);assert.equal(options.redirect,'error');assert.equal(options.credentials,'omit');assert.equal(options.mode,'same-origin');assert.equal(options.referrerPolicy,'no-referrer');return response(url,f.ciphertext)};
 assert.deepEqual(Buffer.from(await h.fetchAttachment(f.ref,f.scope)),f.bytes);assert.equal(calls,1);
 for(const mock of [response('https://evil.invalid/x',f.ciphertext),response(url,f.ciphertext,{redirected:true}),response(url,f.ciphertext,{status:302}),response(url,f.ciphertext,{status:404}),response(url,f.ciphertext,{declared:8000017}),response(url,f.ciphertext.slice(1))]){
  context.fetch=async()=>mock;await assert.rejects(h.fetchAttachment(f.ref,f.scope));
  if(mock.status!==200||mock.redirected||mock.url!==url||Number(mock.headers.get("content-length"))>8000016)assert.equal(mock.cancelled,true);
 }
 const overflow=response(url,new Uint8Array(h.attachmentPaddedSize(f.ref.size)+17),{declared:null});context.fetch=async()=>overflow;
 await assert.rejects(h.fetchAttachment(f.ref,f.scope));assert.equal(overflow.cancelled,true);
 const malformed=response(url,f.ciphertext,{declared:'not-a-number'});context.fetch=async()=>malformed;await assert.rejects(h.fetchAttachment(f.ref,f.scope));
});

test('report endpoint prefers v2 and falls back only on an actual 404',async()=>{
 const {context,h}=load(),json=new TextEncoder().encode(JSON.stringify({v:1,iterations:600000}));let urls=[];
 context.fetch=async(url,options)=>{urls.push(url);assert.equal(options.redirect,'error');return response(url,json)};
 await h.fetchReport();assert.equal(urls.length,1);assert.match(urls[0],/report\.v2\.enc\.json/);
 urls=[];context.fetch=async url=>{urls.push(url);return response(url,json,{status:urls.length===1?404:200})};await h.fetchReport();assert.equal(urls.length,2);assert.match(urls[1],/\/report\.enc\.json/);
 for(const status of [401,403,429,500]){urls=[];context.fetch=async url=>{urls.push(url);return response(url,json,{status})};await assert.rejects(h.fetchReport());assert.equal(urls.length,1)}
 for(const make of [url=>response(url,new TextEncoder().encode('{}')),url=>response(url,json,{redirected:true}),url=>response('https://evil.invalid/x',json),url=>response(url,json,{declared:25000001})]){urls=[];context.fetch=async url=>{urls.push(url);return make(url)};await assert.rejects(h.fetchReport());assert.equal(urls.length,1)}
 urls=[];context.fetch=async url=>{urls.push(url);throw Error('offline')};await assert.rejects(h.fetchReport());assert.equal(urls.length,1);
});

test('legacy and schema2 encrypted reports decrypt with the unchanged report envelope',async()=>{
 const {h}=load(),f=await makeFixture(h),password='synthetic-only';
 const material=await webcrypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveKey']);
 for(const schema of [1,2]){
  const report={...f.report,schema},salt=webcrypto.getRandomValues(new Uint8Array(16)),iv=webcrypto.getRandomValues(new Uint8Array(12));
  const key=await webcrypto.subtle.deriveKey({name:'PBKDF2',salt,iterations:600000,hash:'SHA-256'},material,{name:'AES-GCM',length:256},false,['encrypt']);
  const bytes=await webcrypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:new TextEncoder().encode('promenada-report-v1')},key,new TextEncoder().encode(JSON.stringify(report)));
  const envelope={v:1,iterations:600000,salt:Buffer.from(salt).toString('base64'),iv:Buffer.from(iv).toString('base64'),ciphertext:Buffer.from(bytes).toString('base64')};
  assert.equal(JSON.stringify(await h.decrypt(envelope,material)),JSON.stringify(report));
 }
});

test('legacy download preserves bytes/filename and v2 rendering does not fetch eagerly',async()=>{
 const {h,context}=load(),f=await makeFixture(h);context.setReport(f.report);
 const legacy={name:'oryginał.bin',size:f.bytes.length,base64:f.bytes.toString('base64')};
 const link=h.attachment(legacy);assert.equal(link.download,legacy.name);assert.deepEqual(Buffer.from(await (await fetch(link.href)).arrayBuffer()),f.bytes);
 h.attachment(f.file,f.message,0);assert.equal(context.attachmentURLs.size,1);h.releaseAttachments();assert.equal(context.attachmentURLs.size,0);
 const zero=h.attachment({name:'empty.bin',size:0,base64:''});assert.equal((await (await fetch(zero.href)).arrayBuffer()).byteLength,0);h.releaseAttachments();
});

test('cancel, logout/navigation and late network completions never create a download',async()=>{
 const {h,context}=load(),f=await makeFixture(h);context.setReport(f.report);
 let resolve;
 context.fetch=()=>new Promise(r=>resolve=r);
 const box=h.attachment(f.file,f.message,0),[open,cancel,status]=box.children;
 const pending=open.click();assert.equal(open.disabled,true);cancel.click();resolve(response(h.attachmentURL(f.ref).href,f.ciphertext));await pending;
 assert.match(status.textContent,/anulowane/);assert.equal(open.disabled,false);assert.equal(context.attachmentURLs.size,0);
 const retry=open.click();h.releaseAttachments();context.setReport(null);resolve(response(h.attachmentURL(f.ref).href,f.ciphertext));await retry;
 assert.equal(context.attachmentURLs.size,0);assert.equal(box.children[0],open);
});

test('failure is visible and the same button retries successfully',async()=>{
 const {h,context}=load(),f=await makeFixture(h);context.setReport(f.report);
 let calls=0;context.fetch=async url=>response(url,f.ciphertext,{status:++calls===1?503:200});
 const box=h.attachment(f.file,f.message,0),[open,,status]=box.children;
 await open.click();assert.match(status.textContent,/Nie udało/);assert.match(open.textContent,/Spróbuj ponownie/);
 await open.click();assert.equal(calls,2);assert.equal(box.children[0].download,f.file.name);assert.equal(box.children[0].clicked,true);h.releaseAttachments();
});

test('bundled native bridge sends exact scoped reference and preserves legacy route',async()=>{
 const {h,context,nativeMessages}=load(),f=await makeFixture(h);context.setReport(f.report);
 vm.runInContext(bridge,context);nativeMessages.length=0;
 vm.runInContext('globalThis.nativeAttachment=attachment',context);
 const button=context.nativeAttachment(f.file,f.message,0);button.click();assert.equal(nativeMessages.length,1);
 const sent=nativeMessages[0];assert.deepEqual(JSON.parse(JSON.stringify(sent)),{action:'attachment',name:f.file.name,accountKey:f.scope.accountKey,source:'messages',messageId:f.scope.messageId,attachmentIndex:0,ref:f.ref,scope:{audience:'parent',principal:'parent'}});
 context.nativeAttachment({name:'old.bin',base64:'AA==',size:1}).click();assert.equal(nativeMessages[1].base64,'AA==');assert.equal(nativeMessages[1].ref,undefined);
 let bundled=app.slice(0,app.indexOf('function fromB64('));
 // sync-web.py deliberately removes browser-local persistence initialization.
 const persistenceStart=bundled.indexOf('try{const saved=JSON.parse(localStorage');
 bundled=bundled.slice(0,persistenceStart)+bundled.slice(bundled.indexOf('\nfunction saveReview()',persistenceStart));
 assert.equal(fs.readFileSync(path.join(root,'ios/Promenada/Web/app.js'),'utf8'),bundled+bridge);
});

test('padding buckets hide exact lengths while preserving empty and maximum-size files',async()=>{
 const {h}=load(),f=await makeFixture(h);
 for(const [size,expected] of [[0,65536],[1,65536],[65536,65536],[65537,131072],[7995392,7995392],[7995393,8000000],[8000000,8000000]])assert.equal(h.attachmentPaddedSize(size),expected);
 for(const size of [0,8000000]){
  const bytes=Buffer.alloc(size,165),padded=new Uint8Array(h.attachmentPaddedSize(size));padded.set(bytes);
  const ref={...f.ref,size,sha256:await f.hash(bytes)};
  const key=await webcrypto.subtle.importKey('raw',Buffer.from(ref.key,'base64'),'AES-GCM',false,['encrypt']);
  const ciphertext=new Uint8Array(await webcrypto.subtle.encrypt({name:'AES-GCM',iv:Buffer.from(ref.iv,'base64'),additionalData:h.attachmentAAD(ref,f.scope)},key,padded));
  ref.path='attachments/'+await f.hash(ciphertext)+'.bin';
  assert.equal(ciphertext.length,h.attachmentPaddedSize(size)+16);
  assert.deepEqual(Buffer.from(await h.decryptAttachment(ref,f.scope,ciphertext)),bytes);
 }
});

test('document kind, collection, ID namespace and duplicate IDs must agree',async()=>{
 const {h}=load(),f=await makeFixture(h);
 const clone=()=>JSON.parse(JSON.stringify(f.report));
 for(const mutate of [
  message=>{message.kind='announcement'},
  message=>{message.id=f.scope.accountKey+':announcement:wrong'},
  message=>{message.child='sibling'},
 ]){
  const report=clone();mutate(report.accounts[f.scope.accountKey].messages[0]);
  assert.throws(()=>h.validateReportAccess(report));
 }
 for(const target of ['messages','announcements']){
  const report=clone(),account=report.accounts[f.scope.accountKey];
  account[target].push({...account.messages[0],attachments:[]});
  assert.throws(()=>h.validateReportAccess(report));
 }
 const report=clone(),account=report.accounts[f.scope.accountKey];
 account.messages[0].attachments=[];
 account.announcements.push({...account.messages[0]});
 assert.throws(()=>h.validateReportAccess(report));
 const valid=clone(),m=valid.accounts[f.scope.accountKey].messages.pop();
 m.kind='announcement';m.id=f.scope.accountKey+':announcement:valid';
 valid.accounts[f.scope.accountKey].announcements.push(m);
 h.validateReportAccess(valid);
 assert.equal(h.attachmentContext(valid,m,0,m.attachments[0]).source,'announcements');
});

test('authenticated schema1 at the v2 endpoint is rejected without legacy fallback',async()=>{
 const {h,context}=load(),f=await makeFixture(h),password='synthetic-endpoint-schema';
 const material=await webcrypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveKey']);
 const salt=webcrypto.getRandomValues(new Uint8Array(16)),iv=webcrypto.getRandomValues(new Uint8Array(12));
 const key=await webcrypto.subtle.deriveKey({name:'PBKDF2',salt,iterations:600000,hash:'SHA-256'},material,{name:'AES-GCM',length:256},false,['encrypt']);
 const envelopeFor=async schema=>{
  const bytes=await webcrypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:new TextEncoder().encode('promenada-report-v1')},key,new TextEncoder().encode(JSON.stringify({...f.report,schema})));
  return {v:1,iterations:600000,salt:Buffer.from(salt).toString('base64'),iv:Buffer.from(iv).toString('base64'),ciphertext:Buffer.from(bytes).toString('base64'),expectedSchema:1,schema:1};
 };
 const legacyBytes=new TextEncoder().encode(JSON.stringify(await envelopeFor(1)));
 let calls=[];
 context.fetch=async url=>{calls.push(url);return response(url,legacyBytes)};
 await assert.rejects(h.decrypt(await h.fetchReport(),material));
 assert.equal(calls.length,1);assert.match(calls[0],/report\.v2\.enc\.json/);
 calls=[];context.fetch=async url=>{calls.push(url);return response(url,legacyBytes,{status:calls.length===1?404:200})};
 assert.equal((await h.decrypt(await h.fetchReport(),material)).schema,1);assert.equal(calls.length,2);
 const currentBytes=new TextEncoder().encode(JSON.stringify(await envelopeFor(2)));
 calls=[];context.fetch=async url=>{calls.push(url);return response(url,currentBytes)};
 assert.equal((await h.decrypt(await h.fetchReport(),material)).schema,2);assert.equal(calls.length,1);
 // A server-supplied field cannot downgrade the expected schema, and swapping a v2 report into the legacy URL also fails.
 calls=[];context.fetch=async url=>{calls.push(url);return response(url,currentBytes,{status:calls.length===1?404:200})};
 await assert.rejects(h.decrypt(await h.fetchReport(),material));assert.equal(calls.length,2);
});

test('report requests time out and external/lock cancellation aborts stalled transfers',async()=>{
 for(const mode of ['timeout','external','lock']){
  const {h,context}=load(),external=new AbortController();let timeout,cleared=false,networkSignal;
  context.setTimeout=(callback,ms)=>{assert.equal(ms,30000);timeout=callback;return 42};
  context.clearTimeout=id=>{assert.equal(id,42);cleared=true};
  context.fetch=async (url,{signal})=>{networkSignal=signal;return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new DOMException('Cancelled','AbortError')),{once:true}))};
  const pending=h.fetchReport(external.signal);
  if(mode==='timeout')timeout();else if(mode==='external')external.abort();else h.cancelReportRequests();
  await assert.rejects(pending);assert.equal(networkSignal.aborted,true);assert.equal(cleared,true);
 }
 const {h,context}=load(),external=new AbortController();external.abort();let fetched=false;
 context.fetch=async()=>{fetched=true;throw Error('must not fetch')};await assert.rejects(h.fetchReport(external.signal));assert.equal(fetched,false);
});

test('a stalled report response body is aborted at the same finite deadline',async()=>{
 const {h,context}=load();let timeout,bodyCancelled=false,onRead;const started=new Promise(resolve=>onRead=resolve);
 context.setTimeout=callback=>{timeout=callback;return 1};context.clearTimeout=()=>{};
 context.fetch=async(url,{signal})=>({url,status:200,redirected:false,headers:{get(){return null}},body:{getReader(){return {
  read(){return new Promise((resolve,reject)=>{signal.addEventListener('abort',()=>reject(new DOMException('Cancelled','AbortError')),{once:true});onRead()})},
  async cancel(){bodyCancelled=true},releaseLock(){}
 }}}});
 const pending=h.fetchReport();await started;timeout();
 await assert.rejects(pending);assert.equal(bodyCancelled,true);
});

test('native automatic refresh replaces regenerated refs even with identical collection time/schema',async()=>{
 const {h,context,nativeMessages}=load(),before=await makeFixture(h),after=await makeFixture(h);
 before.report.collected_at=after.report.collected_at='2026-10-05T06:30:00+02:00';
 assert.notEqual(before.ref.path,after.ref.path);
 context.setReport(before.report);vm.runInContext(bridge,context);
 vm.runInContext('globalThis.renders=0;globalThis.healthCalls=0;render=()=>{renders++};renderHealth=()=>{healthCalls++};globalThis.nativeAttachment=attachment;',context);
 // A truly identical manifest preserves the current DOM.
 context.window.promenadaReceive(JSON.parse(JSON.stringify(before.report)),'same',undefined,true);
 assert.equal(context.renders,0);assert.equal(context.healthCalls,1);
 // A replacement key/blob must update JS before the next native open request.
 context.window.promenadaReceive(after.report,'new refs',undefined,true);
 assert.equal(context.renders,1);assert.equal(context.getData(),after.report);
 nativeMessages.length=0;
 context.nativeAttachment(after.file,after.message,0).click();
 assert.equal(nativeMessages.length,1);assert.equal(nativeMessages[0].ref.path,after.ref.path);
 assert.equal(nativeMessages[0].ref.key,after.ref.key);assert.notEqual(nativeMessages[0].ref.key,before.ref.key);
});
