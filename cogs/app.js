const $=s=>document.querySelector(s),mk=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e};
const api=async(u,o)=>{const r=await fetch(u,o);return[r.ok,await r.json()]},post=b=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
let items=[],me=null,groups=[],cur='';
function route(){const p=location.hash.slice(1)||'home';document.querySelectorAll('main>section').forEach(s=>s.hidden=s.id!==p);document.querySelectorAll('nav a.l').forEach(a=>a.classList.toggle('on',a.dataset.p===p));scrollTo(0,0)}
addEventListener('hashchange',route);route();
function draw(){const q=$('#q').value.toLowerCase(),box=$('#items');box.replaceChildren();const l=items.filter(i=>i.name.toLowerCase().includes(q));
if(!l.length)return box.append(mk('p','','Keine Items gefunden.'));
for(const i of l){const c=mk('div','card'),b=mk('div','bar'),p=mk('i');c.append(mk('b','',i.name));p.style.width=(i.stock?100*i.available/i.stock:0)+'%';b.append(p);
c.append(b,mk('small','',(i.available>0?'🟢 ':'🔴 ')+i.available+' / '+i.stock+' verfügbar'));if(i.description)c.append(mk('small','',i.description));
if(me&&i.available>0){const x=mk('button','btn','Leihen');x.style.marginTop='10px';x.onclick=()=>{$('#dn').textContent=i.name;$('#lm').textContent='';$('#dlg').showModal()};c.append(x)}
if(!$('#af').hidden){const e=mk('button','btn g','✏️'),d=mk('button','btn g','🗑');e.style.cssText=d.style.cssText='margin:10px 6px 0 0';
e.onclick=()=>{const f=$('#af').elements;f['name'].value=i.name;f['stock'].value=i.stock;f['description'].value=i.description;$('#af').scrollIntoView()};
d.onclick=async()=>{if(confirm(i.name+' löschen?')){const[ok,j]=await api('/api/item',post({name:i.name,action:'delete'}));$('#am').textContent=j.message;if(ok)load()}};c.append(e,d)}
box.append(c)}}
async function load(){const[ok,d]=await api('/api/items');if(ok){items=d;draw()}}
function drawMembers(f){const box=$('#mem');box.replaceChildren();
for(const g of groups){const l=g.members.filter(u=>!f||(u.skill&&u.skill.name===f));if(!l.length)continue;
const h=mk('h3','',g.label+' ('+l.length+')');h.style.color=g.color;box.append(h);const gr=mk('div','grid');
for(const u of l){const c=mk('div','card mem'),i=mk('img'),t=mk('div');i.src=u.avatar;t.append(mk('span','',u.name),mk('small','',u.ign?'⛏ '+u.ign:'Ingame-Name fehlt'));
if(u.skill){const s=mk('small','',u.skill.name);s.style.color=u.skill.color;t.append(s)}if(u.status)t.append(mk('small','',{opsucht:'🟢 Online · auf OPSUCHT',minecraft:'🟢 Online · spielt Minecraft',online:'🟢 Online',offline:'⚫ Offline'}[u.status]));c.append(i,t);gr.append(c)}box.append(gr)}
if(!box.children.length)box.append(mk('p','','Keine Mitglieder gefunden.'))}
async function init(){
const[,m]=await api('/api/me');me=m.user;$('#rf').hidden=!m.leader;$('#kf').hidden=!m.leader;$('#af').hidden=!m.staff;$('#ig').hidden=!(me&&!m.ign);const a=$('#auth');
if(me){const i=mk('img');i.src=m.ign?'https://crafthead.net/helm/'+m.ign+'/64':(me.avatar||'');i.width=28;i.style.cssText='border-radius:50%;vertical-align:middle;margin-right:8px';const o=mk('a','','Abmelden');o.href='/logout';o.style.color='var(--o)';a.append(i,me.name+' · ',o);$('#f [name=discord]').value=me.username}
else if(m.login){const b=mk('a','btn','Anmelden');b.href='/login';a.append(b)}
$('#hint').textContent=me?'Wähle ein Item und klicke auf „Leihen“.':'Melde dich an, um Items zu leihen.';
const[,s]=await api('/api/stats');$('#s1').textContent=s.clan;$('#s2').textContent=s.leiher;
const[,r]=await api('/api/rules');const clean=t=>t.replace(/^[^\p{L}\s]+\s/u,'');for(const t of r.rules)$('#rules').append(mk('li','',clean(t)));$('#rt').value=r.rules.map(clean).join('\n');
if(!r.rules.length)$('#rules').append(mk('li','','Noch keine Regeln eingetragen.'));
for(const n of['Alle','Farmer','Builder','Miner']){const b=mk('button','btn g',n);b.onclick=()=>drawMembers(cur=n==='Alle'?'':n);$('#flt').append(b)}
[,groups]=await api('/api/members');drawMembers('');
load();setInterval(load,30000)}
$('#q').oninput=draw;init();
$('#lf').onsubmit=async e=>{e.preventDefault();const f=Object.fromEntries(new FormData(e.target));f.item=$('#dn').textContent;
const[ok,j]=await api('/api/leihen',post(f));$('#lm').textContent=j.message;if(ok)setTimeout(()=>{$('#dlg').close();load()},1500)};
$('#f').onsubmit=async e=>{e.preventDefault();const b=$('#f button'),m=$('#msg');b.disabled=true;m.textContent='Sende …';
try{const[ok,j]=await api('/api/bewerbung',post(Object.fromEntries(new FormData(e.target))));m.textContent=j.message;if(ok)e.target.reset()}catch(x){m.textContent='Fehler beim Senden.'}b.disabled=false};
$('#rf').onsubmit=async e=>{e.preventDefault();const[ok,j]=await api('/api/regeln',post({rules:$('#rt').value}));$('#rm').textContent=j.message;if(ok)setTimeout(()=>location.reload(),900)};
$('#af').onsubmit=async e=>{e.preventDefault();const f=Object.fromEntries(new FormData(e.target));f.stock=+f.stock;const[,j]=await api('/api/item',post(f));$('#am').textContent=j.message;load()};
 
const fmt=v=>v==null?'–':Number(v).toLocaleString('de-DE')+' $';
async function loadKonto(){const[,k]=await api('/api/konto'),g=$('#kg');g.replaceChildren();
for(const[l,v]of[['Kontostand',k.balance],['Heute',k.day],['Diese Woche',k.week],['Dieser Monat',k.month]]){
const c=mk('div','card'),b=mk('b','',fmt(v));b.style.cssText='display:block;font-size:1.6rem;color:var(--o)';c.append(mk('small','',l),b);g.append(c)}
$('#ku').textContent=k.updated?'Zuletzt aktualisiert: '+new Date(k.updated).toLocaleString('de-DE')+(k.by?' von '+k.by:''):'Noch keine Angaben.';
const f=$('#kf').elements;for(const n of['balance','day','week','month'])if(k[n]!=null)f[n].value=k[n]}
$('#kf').onsubmit=async e=>{e.preventDefault();const f=Object.fromEntries(new FormData(e.target));for(const k in f)f[k]=+f[k];
const[ok,j]=await api('/api/konto',post(f));$('#km').textContent=j.message;if(ok)loadKonto()};
loadKonto();setInterval(loadKonto,60000);
 
$('#ig').onsubmit=async e=>{e.preventDefault();const[ok,j]=await api('/api/ign',post({name:e.target.elements['name'].value}));$('#igm').textContent=j.message;if(ok)setTimeout(()=>location.reload(),700)};
setInterval(async()=>{const[ok,g]=await api('/api/members');if(ok){groups=g;drawMembers(cur)}},60000);
 
const opsData={},opsSort={};
function opsTable(k){const box=document.querySelector('#'+k+' .tw'),q=document.querySelector('#'+k+' input').value.toLowerCase();box.replaceChildren();
let rows=opsData[k];if(!rows)return;
if(!Array.isArray(rows)){const row=([n,v])=>typeof v==='object'&&v?{name:n,...v}:{name:n,wert:v},vals=Object.values(rows),objs=vals.filter(v=>v&&typeof v==='object'&&!Array.isArray(v));
if(objs.length>5&&objs.length>vals.length/2)rows=Object.entries(rows).map(row);
else{const sets=vals.map(v=>Array.isArray(v)?v:(v&&typeof v==='object'?Object.entries(v).map(row):null)).filter(Boolean).sort((a,b)=>b.length-a.length);
rows=sets[0]||Object.entries(rows).map(row)}}
const s=opsSort[k];let l=rows.filter(r=>JSON.stringify(r).toLowerCase().includes(q));
if(s)l.sort((a,b)=>{const x=a[s.c],y=b[s.c];return(typeof x==='number'&&typeof y==='number'?x-y:String(x??'').localeCompare(String(y??''),'de'))*s.dir});l=l.slice(0,500);
if(!l.length)return box.append(mk('p','','Keine Einträge.'));
const cols=[];for(const r of rows.slice(0,50))for(const[c,v]of Object.entries(r))if((typeof v!=='object'||v===null)&&!cols.includes(c)&&cols.length<7)cols.push(c);
const t=mk('table'),h=mk('tr');for(const c of cols){const th=mk('th','',c+(s&&s.c===c?(s.dir>0?' ▲':' ▼'):''));th.style.cursor='pointer';th.onclick=()=>{opsSort[k]={c,dir:s&&s.c===c?-s.dir:1};opsTable(k)};h.append(th)}t.append(h);
for(const r of l){const tr=mk('tr');for(const c of cols){const v=r[c];tr.append(mk('td','',typeof v==='number'?v.toLocaleString('de-DE'):String(v??'').slice(0,60)))}t.append(tr)}
box.append(t)}
async function loadOps(k){const[ok,d]=await api('/api/ops/'+k),box=document.querySelector('#'+k+' .tw');if(!ok){box.textContent=d.message;return}opsData[k]=d;opsTable(k)}
for(const k of['shards','markt','ah']){document.querySelector('#'+k+' input').oninput=()=>opsTable(k);loadOps(k);setInterval(()=>loadOps(k),60000)}
