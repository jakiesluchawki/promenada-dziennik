// Render the actual web/native reader with synthetic children and no network.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function element(tag){return {tag,children:[],attributes:{},dataset:{},listeners:{},classList:{add(){}},value:'',append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},setAttribute(k,v){this.attributes[k]=v},removeAttribute(k){delete this.attributes[k]},addEventListener(k,v){this.listeners[k]=v},click(){this.listeners.click?.()},focus(){},after(){},querySelectorAll(){return []}}}
const text=n=>[n.textContent||'',...(n.children||[]).map(text)].join(' ');
function load(native){
 const nodes=new Map(),doc={getElementById(id){if(!nodes.has(id))nodes.set(id,element('div'));return nodes.get(id)},createElement:element,createElementNS:(_,tag)=>element(tag),createTextNode:t=>({textContent:t}),querySelectorAll:()=>[],querySelector:()=>element('a')};
 const context={document:doc,window:{scrollTo(){},webkit:{messageHandlers:{journal:{postMessage(){}}}}},localStorage:{getItem:()=>null},URL,TextEncoder,AbortController,console};
 vm.createContext(context);
 let src=fs.readFileSync(native?'ios/Promenada/Web/app.js':'app.js','utf8');
 if(!native)src=src.slice(0,src.indexOf('$("unlock-form").addEventListener'))+src.slice(src.indexOf('function lock(){'),src.indexOf('$("lock").addEventListener'));
 vm.runInContext(src,context);
 return {nodes,context,run:code=>vm.runInContext(code,context)};
}
function fixture(){
 const accounts={};
 for(const child of ['alpha','beta']) accounts[child]={child,name:child==='alpha'?'Dziecko A':'Dziecko B',role:'parent',status:'ok',checked_at:new Date().toISOString(),messages:[{id:child+':message:demo',child,kind:'message',title:'Wiadomość '+child,text:'Treść '+child,sender:'Test',date:'2026-10-05',revision:child+'-mail',attachments:[]}],announcements:[],sections:{}};
 return {schema:1,collected_at:new Date().toISOString(),accounts,digest:{actions:['alpha','beta'].map(child=>({id:child+':action',child,title:'Sprawa '+child,priority:'info',revision:child+'-task'})),observations:['alpha','beta'].map(child=>({id:child+':observation',child,title:'Uwaga '+child,priority:'info'}))}};
}
for(const native of [false,true]) test(`${native?'native':'web'}: one child across overview, inbox, refresh and logout`,()=>{
 const {nodes,context,run}=load(native);context.fixture=fixture();run('data=fixture;render()');
 assert.deepEqual(nodes.get('children').children.map(b=>b.textContent),['Dziecko A','Dziecko B']);
 assert.equal(run('selected'),'alpha');
 assert.match(text(nodes.get('main')),/Dziennik: Dziecko A/);
 assert.match(text(nodes.get('main')),/Sprawa alpha/);assert.doesNotMatch(text(nodes.get('main')),/beta|Dziecko B/);
 run('query="stary filtr";attentionFilter="urgent";documentFilter="new"');
 nodes.get('children').children[1].click();
 assert.equal(run('query'),'');assert.equal(run('attentionFilter'),'all');assert.equal(run('documentFilter'),'all');
 assert.match(text(nodes.get('main')),/Sprawa beta/);assert.doesNotMatch(text(nodes.get('main')),/alpha|Dziecko A/);
 assert.equal(nodes.get('children').children[1].attributes['aria-pressed'],'true');
 run('navigate("messages")');assert.match(text(nodes.get('main')),/Wiadomość beta/);assert.doesNotMatch(text(nodes.get('main')),/Wiadomość alpha/);
 assert.equal(run('newCount("messages")'),1);assert.equal(run('getDocuments().length'),1);
 if(native)run('window.promenadaReceive(fixture,"",null,true)');else run('data=fixture;render()');
 assert.equal(run('selected'),'beta');
 // A disappeared child must fall back to one valid child, never a combined view.
 run('data={...fixture,accounts:{alpha:fixture.accounts.alpha}};render()');assert.equal(run('selected'),'alpha');
 assert.match(text(nodes.get('main')),/Dziennik: Dziecko A/);assert.doesNotMatch(text(nodes.get('main')),/Wiadomość beta/);
 if(native)run('window.promenadaClear()');else run('lock()');
 assert.equal(run('selected'),null);assert.equal(run('data'),null);
});

test('child colours follow identity rather than report order',()=>{
 const {context,run}=load(false);context.fixture=fixture();
 run('data={accounts:{kostek:{child:"kostek",name:"Kostek"},witek:{child:"witek",name:"Witek"}}}');
 assert.equal(run('childTone("kostek")'),'olive');assert.equal(run('childTone("witek")'),'blue');
 run('data={accounts:{witek:data.accounts.witek,kostek:data.accounts.kostek}}');
 assert.equal(run('childTone("kostek")'),'olive');assert.equal(run('childTone("witek")'),'blue');
});
