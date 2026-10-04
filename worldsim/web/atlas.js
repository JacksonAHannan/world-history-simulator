'use strict';

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = value => new Intl.NumberFormat('en', {maximumFractionDigits:0}).format(value);
const compact = value => new Intl.NumberFormat('en', {notation:'compact',maximumFractionDigits:1}).format(value);
const labelYear = (offset, start=-9000) => {const astronomical = start + (start < 0 ? 1 : 0) + offset;const year = astronomical <= 0 ? astronomical-1 : astronomical;return `${number(Math.abs(year))} ${year < 0 ? 'BCE' : 'CE'}`;};
const human = text => String(text).replaceAll('_',' ').replace(/([a-z])([A-Z])/g,'$1 $2');
const color = id => id < 0 ? '#c4cdbb' : `hsl(${(id*137.508+37)%360} 34% 63%)`;
const icons = {
 terrain:'M2 17 8 6l4 7 3-5 7 9Z', water:'M3 6c4 0 4 4 8 4s4-4 8-4M3 13c4 0 4 4 8 4s4-4 8-4',
 food:'M12 21V5M12 12C4 12 4 4 4 4c7 0 8 8 8 8Zm0 5c8 0 8-8 8-8-7 0-8 8-8 8Z',
 city:'M3 21V9h7v12M10 21V3h10v18M5 13h3m-3 4h3m5-10h4m-4 4h4m-4 4h4M1 21h22',
 population:'M8 13a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm9-3a3 3 0 1 0 0-6M2 21v-2c0-5 12-5 12 0v2m3-7c4 0 5 2 5 5v2',
 language:'M3 4h13M9 2v3m-5 3c1 5 5 8 10 10M13 5c0 6-4 10-10 13m11 4 4-12 4 12m-6-4h5',
 culture:'M3 8h18M5 8v12m7-12v12m7-12v12M2 21h20M2 6l10-4 10 4',
 faith:'M12 2v20M4 8h16M5 20c2-5 12-5 14 0',
 polity:'M5 22V3m0 0c5-5 9 5 15 0v10c-6 5-10-5-15 0',
 trade:'M2 8h18m-4-4 4 4-4 4M22 16H4m4-4-4 4 4 4',
 technology:'M8 2v5l-5 12c-1 2 1 3 3 3h12c2 0 4-1 3-3L16 7V2M6 2h12M6 15h12',
 war:'M4 3 18 17m2 3-5-5m0 5 5-5M20 3 6 17m-2 3 5-5m0 5-5-5',
 displacement:'M4 20V7h8v13M2 20h12m0-7h8m-3-3 3 3-3 3',
 ecology:'M12 21V11M4 5c0 10 8 10 8 6 0-7-8-6-8-6Zm8 10c0-10 8-10 8-6 0 7-8 6-8 6Z'
};
const layers = [
 ['terrain','Topography','terrain'],['basin','Watersheds','water'],['food','Food reserves','food'],
 ['settlement','Settlements','city'],['population','Population','population'],['language','Languages','language'],
 ['community','Communities','culture'],['belief','Faiths','faith'],['political','Political control','polity'],
 ['trade','Trade routes','trade'],['technology','Technology','technology'],['war','Conflict & claims','war'],
 ['migration','Population movement','displacement'],['displacement','War displacement','displacement'],['ecology','Environment','ecology']
];
const state = {runs:[], run:null, data:null, layer:'terrain', year:0, timeline:[], selected:null, tab:'inspect',
 job:{running:false},zoom:1,pan:{x:0,y:0}, request:0, transform:null, inspecting:0};
let toastTimer, scrubTimer, dragging=null, moved=false;

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data = await response.json();
  if(!response.ok) throw new Error(data.error?.message || `Request failed (${response.status}).`);
  return data;
}
function toast(message) { $('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6000); }
function report(error) {console.error(error);toast(error.message || String(error));}
function path(operation, query={}) {const params = new URLSearchParams(query);return `/api/run/${state.run}/${operation}${params.size?'?'+params:''}`;}

function initLayers(){
  $('layer-buttons').innerHTML=layers.map(([key,name,icon])=>`<button class="layer-button ${key===state.layer?'active':''}" data-layer="${key}" aria-pressed="${key===state.layer}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="${icons[icon]}"/></svg>${esc(name)}</button>`).join('');
  $('layer-buttons').addEventListener('click',event=>{const button=event.target.closest('[data-layer]');if(!button)return;state.layer=button.dataset.layer;document.querySelectorAll('[data-layer]').forEach(b=>{b.classList.toggle('active',b===button);b.setAttribute('aria-pressed',String(b===button));});drawMap();renderLegend();});
}
async function loadRuns(preferred) {
  const data = await api('/api/runs');state.runs=data.runs;
  $('run-select').innerHTML=state.runs.length?state.runs.map(r=>`<option value="${r.id}">${r.parent?'Branch of ':''}World ${r.seed} · ${compact(r.population)} people${r.can_simulate?'':' · earlier model'}</option>`).join(''):'<option value="">No worlds yet</option>';
  if(!state.runs.length){$('empty').hidden=false;return;}
  const run = state.runs.find(r=>r.id===preferred)||state.runs.find(r=>r.id===state.run)||state.runs[0];
  $('run-select').value=run.id;
  if(state.run!==run.id) await selectRun(run.id);
}
async function selectRun(id){
  state.run=id;state.selected=null;state.zoom=1;state.pan={x:0,y:0};state.job=state.runs.find(r=>r.id===id)?.job||{};
  state.tab='inspect';updateTabs();await refreshTimeline();await loadWorld();
  $('search').value='';$('search-results').hidden=true;renderPanel();
}
async function refreshTimeline(){if(!state.run)return;const data=await api(path('timeline'));state.timeline=data.timeline;drawTimeline();}
async function loadWorld(year){
  if(!state.run)return;const token=++state.request;const data=await api(path('world',year===undefined?{}:{year}));if(token!==state.request)return;
  state.data=data;state.year=data.summary.year;$('empty').hidden=true;$('export').disabled=false;$('run').disabled=!data.summary.can_simulate;
  $('date').textContent=data.summary.date;$('world-meta').textContent=`World ${data.summary.seed} · ${number(data.provinces.length)} regions${data.summary.parent?' · intervention branch':''}`;
  $('stats').innerHTML=`<div class="stat"><strong>${compact(data.summary.population)}</strong><span>People</span></div><div class="stat"><strong>${number(data.summary.languages)}</strong><span>Living languages</span></div><div class="stat"><strong>${number(data.summary.polities)}</strong><span>Polities</span></div>`;
  $('year').disabled=false;$('year').max=data.summary.latest_year;$('year').value=state.year;
  $('first-year').textContent=labelYear(0,data.summary.start_year);$('view-year').textContent=`${data.summary.date} · year ${number(state.year)}`;
  $('latest-year').textContent=labelYear(data.summary.latest_year,data.summary.start_year);
  $('timeline-caption').textContent=data.summary.can_simulate?`${number(data.summary.latest_year)} annual transitions recorded. Scrub to inspect any saved year.`:'Saved history from the earlier population model. Generate a new world with this seed to use food-limited populations and cities.';
  drawMap();drawTimeline();renderLegend();await renderPanel();
}

function setupCanvas(canvas){const rect=canvas.getBoundingClientRect();const dpr=window.devicePixelRatio||1;const width=Math.max(1,rect.width),height=Math.max(1,rect.height);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);return {ctx,width,height};}
function terrain(p){
  if(p.lake_depth_m>80)return '#95c4d7';
  if(p.elevation_m>1800)return p.elevation_m>2500?'#e4e3da':'#b6b5a7';
  return ({'alpine':'#b7b6a6','tundra':'#ced4c2','boreal forest':'#94b498','desert':'#d6c49a','grassland':'#c0c69a','rainforest':'#739c81','temperate forest':'#a2bb93'})[p.biome]||'#bdcba2';
}
function provinceColor(p){switch(state.layer){
  case 'terrain':case 'settlement':case 'trade':return terrain(p);
  case 'basin':return color(p.basin);
  case 'food':return `hsl(${42+Math.min(3,p.food_years)*35} 34% ${82-Math.min(3,p.food_years)*12}%)`;
  case 'population':return p.population?`hsl(205 38% ${86-Math.min(1,Math.log1p(p.density)/3)*52}%)`:'#d0d9cb';
  case 'language':return color(p.language);
  case 'community':return color(p.community);
  case 'belief':return color(p.belief);
  case 'political':return color(p.control);
  case 'technology':return `hsl(${200-p.technology.length*3} ${20+p.technology.length}% ${85-p.technology.length*2}%)`;
  case 'war':return p.war?'#b77564':color(p.control);
  case 'migration':
  case 'displacement':return p[state.layer]?`hsl(28 52% ${80-Math.min(1,Math.log1p(p[state.layer])/8)*40}%)`:'#cbd7d5';
  case 'ecology':return `hsl(${140-Math.min(1,p.pollution)*100} 25% ${75-Math.min(1,p.pollution)*20}%)`;
  default:return terrain(p);
}}
function drawMap(){
  const {ctx,width,height}=setupCanvas($('map'));ctx.fillStyle='#dcecf3';ctx.fillRect(0,0,width,height);if(!state.data)return;
  const fit=Math.min((width-28)/360,(height-105)/136),scale=fit*state.zoom;
  const cx=width/2+state.pan.x,cy=height/2+12+state.pan.y;state.transform={scale,cx,cy,width,height};
  ctx.save();ctx.translate(cx,cy);ctx.scale(scale,scale);
  ctx.strokeStyle='#b6d0df';ctx.lineWidth=.5/scale;
  for(let lon=-180;lon<=180;lon+=30){ctx.beginPath();ctx.moveTo(lon,-68);ctx.lineTo(lon,68);ctx.stroke();}
  for(let lat=-60;lat<=60;lat+=15){ctx.beginPath();ctx.moveTo(-180,-lat);ctx.lineTo(180,-lat);ctx.stroke();}
  ctx.strokeStyle='#99bfce';ctx.lineWidth=.8/scale;ctx.strokeRect(-180,-68,360,136);
  for(const p of state.data.provinces){
    const g=p.geometry,x=g[0][0],y=-g[2][1],w=g[1][0]-x,h=g[2][1]-g[0][1];
    ctx.fillStyle=provinceColor(p);ctx.fillRect(x,y,w+.035,h+.035);
    ctx.strokeStyle=['political','language','community','belief','war','basin'].includes(state.layer)?'#ffffff39':'#38514414';ctx.lineWidth=.5/scale;ctx.strokeRect(x,y,w,h);
    if(state.layer==='terrain'&&p.elevation_m>1000){ctx.fillStyle='#4b514414';ctx.fillRect(x,y,w,h*.14);}
  }
  if(['terrain','basin','settlement','trade','food'].includes(state.layer)){
    for(const p of state.data.provinces){if(p.river_flow<1300)continue;const parent=state.data.provinces[p.drainage];if(parent&&Math.abs(parent.longitude-p.longitude)<180){ctx.strokeStyle='#578faa';ctx.lineWidth=Math.min(2.2,.4+Math.log(p.river_flow/1300)*.45)/scale;ctx.beginPath();ctx.moveTo(p.longitude,-p.latitude);ctx.lineTo(parent.longitude,-parent.latitude);ctx.stroke();}else if(!parent){ctx.fillStyle='#6aa1b9';ctx.beginPath();ctx.arc(p.longitude,-p.latitude,1/scale,0,Math.PI*2);ctx.fill();}}
  }
  if(state.layer==='trade')for(const flow of state.data.trade){const a=state.data.provinces[flow.from],b=state.data.provinces[flow.to];if(Math.abs(a.longitude-b.longitude)>180)continue;ctx.strokeStyle='#ae765ec9';ctx.lineWidth=Math.min(3,1+Math.log1p(flow.food)/5)/scale;ctx.setLineDash([4/scale,3/scale]);ctx.beginPath();ctx.moveTo(a.longitude,-a.latitude);ctx.lineTo(b.longitude,-b.latitude);ctx.stroke();ctx.setLineDash([]);}
  const labelCandidates=state.data.provinces.filter(p=>p.population>0).sort((a,b)=>b.population-a.population).slice(0,Math.round(5+state.zoom*3));
  const placed=[];
  if(['terrain','settlement','political','trade'].includes(state.layer))for(const p of labelCandidates){
    const radius=Math.min(5,1.5+Math.log1p(p.urban_population||p.population)/5)/scale;
    ctx.fillStyle=p.urban_population>=state.data.summary.city_min_population?'#17334a':'#466256';ctx.strokeStyle='#f6f9eccc';ctx.lineWidth=1/scale;ctx.beginPath();ctx.arc(p.longitude,-p.latitude,radius,0,Math.PI*2);ctx.fill();ctx.stroke();
    const px=cx+p.longitude*scale,py=cy-p.latitude*scale;if(px<40||px>width-70||py<75||py>height-80||placed.some(q=>Math.abs(q.x-px)<95&&Math.abs(q.y-py)<23))continue;
    placed.push({x:px,y:py});const text=p.name.length>18?p.name.slice(0,17)+'…':p.name;ctx.font=`${11/scale}px ${getComputedStyle(document.body).fontFamily}`;ctx.lineWidth=3/scale;ctx.strokeStyle='#edf3e2df';ctx.strokeText(text,p.longitude+7/scale,-p.latitude+3/scale);ctx.fillStyle='#294133';ctx.fillText(text,p.longitude+7/scale,-p.latitude+3/scale);
  }
  if(state.selected?.kind==='province'){const p=state.data.provinces[state.selected.id];if(p){const g=p.geometry;ctx.strokeStyle='#fff';ctx.lineWidth=4/scale;ctx.strokeRect(g[0][0],-g[2][1],g[1][0]-g[0][0],g[2][1]-g[0][1]);ctx.strokeStyle='#bc8430';ctx.lineWidth=2/scale;ctx.strokeRect(g[0][0],-g[2][1],g[1][0]-g[0][0],g[2][1]-g[0][1]);}}
  ctx.restore();
  ctx.font='9px '+getComputedStyle(document.body).fontFamily;ctx.fillStyle='#587d93';ctx.fillText('N',width-24,97);ctx.beginPath();ctx.moveTo(width-22,108);ctx.lineTo(width-26,115);ctx.lineTo(width-18,115);ctx.closePath();ctx.fill();
}
function hitMap(clientX,clientY){if(!state.data||!state.transform)return null;const rect=$('map').getBoundingClientRect();const t=state.transform;const lon=(clientX-rect.left-t.cx)/t.scale,lat=-(clientY-rect.top-t.cy)/t.scale;if(lon<-180||lon>=180||lat<-68||lat>=68)return null;const grid=state.data.grid,col=Math.floor((lon+180)/360*grid.width),row=Math.floor((68-lat)/136*grid.height);const pid=grid.cells[row*grid.width+col];return pid>=0?state.data.provinces[pid]:null;}
function renderLegend(){if(!state.data)return;const name=layers.find(l=>l[0]===state.layer)[1];let body='';
  const ramp=(colors,left,right)=>`<div class="legend-ramp" style="background:linear-gradient(90deg,${colors})"></div><div class="legend-labels"><span>${left}</span><span>${right}</span></div>`;
  if(state.layer==='terrain')body=ramp('#739c81,#c0c69a,#d6c49a,#b6b5a7,#e4e3da','Lowlands','High relief · m');
  else if(state.layer==='population')body=ramp('#d0d9cb,#abc6d8,#365e7a','0','People / km² · counts');
  else if(state.layer==='food')body=ramp('#ddd2b9,#abc49b,#548558','0','3 consumption years');
  else if(['language','political','belief','community'].includes(state.layer)){const field=state.layer==='political'?'control':state.layer;const catalog=state.layer==='political'?'polities':state.layer==='language'?'languages':state.layer==='community'?'communities':'beliefs';const totals=new Map();for(const p of state.data.provinces)totals.set(p[field],(totals.get(p[field])||0)+p.population);body=[...totals.entries()].sort((a,b)=>b[1]-a[1]).slice(0,4).map(([id])=>`<div class="legend-item"><i style="background:${color(id)}"></i>${esc(id<0?(field==='control'?'Local autonomy':'No recorded residents'):state.data[catalog][id]?.name||id)}</div>`).join('');}
  else if(state.layer==='basin')body='Colors identify distinct drainage basins.';
  else if(state.layer==='settlement')body=`<div class="legend-item"><i style="background:#17334a"></i>City · ${number(state.data.summary.city_min_population)}+ urban residents</div><div class="legend-item"><i style="background:#466256"></i>Other settlement</div>`;
  else if(state.layer==='trade')body='Dashed lines: recorded food shipments this year.';
  else if(state.layer==='technology')body=ramp('#d1dbe2,#498c96','0','23 adopted capabilities');
  else if(state.layer==='war')body='<div class="legend-item"><i style="background:#b77564"></i>Active contested objective</div><span>Other colors: effective control</span>';
  else if(state.layer==='migration')body=ramp('#cbd7d5,#c78855','0','All departures this year · counts');
  else if(state.layer==='displacement')body=ramp('#cbd7d5,#c78855','0','War refugees this year · counts');
  else body=ramp('#aec9ba,#b6a284','Low','Pollution index · estimate');
  $('legend').innerHTML=`<span class="legend-title">${esc(name)}</span>${body}`;
}
function drawTimeline(){const {ctx,width,height}=setupCanvas($('timeline-chart'));ctx.clearRect(0,0,width,height);if(!state.timeline.length)return;const end=state.timeline.at(-1).year;const max=Math.max(...state.timeline.map(x=>x.population),1);const step=Math.max(1,Math.floor(state.timeline.length/width));const points=state.timeline.filter((_,i)=>i%step===0);ctx.beginPath();ctx.moveTo(0,height);for(const p of points)ctx.lineTo(p.year/Math.max(1,end)*width,height-5-p.population/max*(height-12));ctx.lineTo(width,height);ctx.closePath();ctx.fillStyle='#dceaf2';ctx.fill();ctx.beginPath();for(const [i,p] of points.entries()){const x=p.year/Math.max(1,end)*width,y=height-5-p.population/max*(height-12);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);}ctx.strokeStyle='#6796b3';ctx.lineWidth=1.3;ctx.stroke();const x=state.year/Math.max(1,end)*width;ctx.strokeStyle='#bc8430';ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,height);ctx.stroke();}

function updateTabs(){for(const tab of ['inspect','history','compare'])$(`${tab}-tab`).setAttribute('aria-selected',String(state.tab===tab));}
async function selectEntity(kind,id){state.selected={kind,id:Number(id)};state.tab='inspect';updateTabs();drawMap();$('search-results').hidden=true;await renderPanel();}
function pairs(values){return `<dl class="detail-pairs">${values.map(([key,value])=>`<dt>${esc(key)}</dt><dd>${value}</dd>`).join('')}</dl>`;}
function section(title,body){return `<section class="detail-section"><h3>${esc(title)}</h3>${body}</section>`;}
function eventsHTML(events){if(!events.length)return '<p class="muted">No major events recorded at this date. Routine births, deaths and flows are retained in annual accounting.</p>';return events.map(e=>`<div class="event-row"><div class="event-date">${labelYear(e.year,state.data.summary.start_year)}</div><button data-event="${esc(e.id)}">${esc(e.text)}</button><span class="event-type">${esc(human(e.type))}</span></div>`).join('');}
async function renderPanel(){
  if(!state.data)return;const content=$('dossier-content');const request=++state.inspecting;
  if(state.tab==='history'){
    const query={year:state.year,limit:100};
    if(state.selected)query.entity=`${state.selected.kind}:${state.selected.id}`;
    if(state.historyType)query.type=state.historyType;
    const result=await api(path('events',query));
    if(request!==state.inspecting)return;
    const types=['StateFormation','Conquest','Secession','Treaty','Battle','ConflictStarted','CityGrowth','LanguageSplit','SoundChange','Borrowing','LanguageShift','Discovery','Adoption','Abandonment','CropFailure','Epidemic','Migration','Displacement'];
    content.innerHTML=`<div class="entity-kind">Recorded history · ${esc(state.data.summary.date)}</div><h2 class="entity-title">${state.selected?'Changes here':'A world in motion'}</h2><p class="entity-subtitle">Select an entry to trace its conditions and earlier events.</p><label for="history-type">Event type</label><select id="history-type" class="comparison-select"><option value="">All recorded events</option>${types.map(type=>`<option value="${type}" ${state.historyType===type?'selected':''}>${esc(human(type))}</option>`).join('')}</select>${eventsHTML(result.events)}`;
    return;
  }
  if(state.tab==='compare'){renderCompare();return;}
  if(!state.selected){content.innerHTML=`<div class="dossier-intro"><h2>Follow a place through time</h2><p>Select a region on the map, or search for a language or polity. Every date opens a different chapter.</p></div>${section('Places to begin',`<div class="province-list">${[...state.data.provinces].sort((a,b)=>b.population-a.population).slice(0,6).map(p=>`<button data-entity="province:${p.id}">${esc(p.name)}<small>${number(p.population)} people · ${esc(p.biome)}</small></button>`).join('')}</div>`)}`;return;}
  let d;try{d=await api(path('dossier',{kind:state.selected.kind,id:state.selected.id,year:state.year}));}catch(error){if(request===state.inspecting)content.innerHTML=`<p class="inline-error">${esc(error.message)}</p>`;return;}if(request!==state.inspecting)return;
  const details=d.details;let html=`<p class="entity-kind">${esc(human(d.kind))} · ${esc(d.date)}</p><h2 class="entity-title">${esc(d.name)}</h2><p class="entity-subtitle">${d.kind==='language'?'Language variety':d.kind==='polity'?esc(details.form):esc(details.biome||'Settlement')} · ${number(d.population)} ${d.kind==='language'?'speakers':'residents'}</p>`;
  html+=section('People',pairs([[d.population_is_estimate?'Population estimate':'Population',number(d.population)],['Local communities',number(Object.keys(d.community_shares).length)],['Belief traditions',number(Object.keys(d.belief_shares).length)]]));
  if(d.population_is_estimate)html+='<p class="callout">City residents and their composition are estimated from the region’s urban share.</p>';if(d.population){const maximum=Math.max(...d.age_structure,1);html+=`<div class="age-chart" aria-label="Population by five-year age band">${d.age_structure.map((c,i)=>`<i title="${i===17?'85+':i*5+'–'+(i*5+4)}: ${number(c)}" style="height:${Math.max(1,c/maximum*100)}%"></i>`).join('')}</div><div class="age-labels"><span>0–4</span><span>Age in years</span><span>85+</span></div>`;}
  if(d.kind==='province'){
    html+=section('Land & livelihood',pairs([['Area',`${number(details.area_km2)} km²`],['Elevation',`${number(details.elevation_m)} m`],['Annual rain',`${number(details.rain_mm)} mm`],['Growing season',`${details.growing_days} days`],['Arable share',`${Math.round(details.arable_share*100)}%`],['Food reserves',`${(details.food/Math.max(d.population,1)).toFixed(2)} years`]]));
    if(details.subsistence){const food=details.subsistence;html+=section('Food & settlement support',pairs([['Cultivated land',`${number(food.cultivated_ha)} ha`],['Harvest',food.harvest===null?'No annual harvest recorded':`${number(food.harvest)} annual rations`],['Food producers',food.food_workers===null?'No annual record':number(food.food_workers)],['City food support',`${number(food.urban_food_support)} residents`],['Sustained surplus',`${number(food.surplus_years)} years`]]));}
    const polity=state.data.polities[details.control];html+=section('Governing layers',polity?`<button class="text-button" data-entity="polity:${details.control}">${esc(polity.name)}</button><p>Effective control; local communities and languages persist separately.</p>`:'<p>Local autonomy. No central polity controls this region.</p>');
    if(details.settlements?.length)html+=section('Settlements',details.settlements.map(s=>`<p><button class="text-button" data-entity="settlement:${s.id}">${esc(s.name)}</button> · ${s.city_founded!==null?'city':'local settlement'}</p>`).join(''));
    html+=section('Names over time',`<p>${esc(details.etymology.meaning)}. A ${esc(details.etymology.formation)} in <button class="text-button" data-entity="language:${details.etymology.language}">${esc(state.data.languages[details.etymology.language]?.name)}</button>.</p>`);
    html+=`<div class="dossier-actions"><button id="branch-here">Branch this region</button><button id="show-accounting">Annual accounting</button></div>`;
  }
  if(d.language_shares.length)html+=section('Languages',d.language_shares.map(l=>`<div class="share-row"><button data-entity="language:${l.id}"><span>${esc(l.name)}</span><span>${(l.speakers/Math.max(d.population,1)*100).toFixed(1)}%</span></button><div class="share-track"><i style="width:${l.speakers/Math.max(d.population,1)*100}%;background:${color(l.id)}"></i></div></div>`).join(''));
  if(details.adopted)html+=section('Capabilities in use',details.adopted.length?`<div class="capabilities">${details.adopted.map(t=>`<span class="capability">${esc(human(t))}</span>`).join('')}</div>`:'<p>Foraging and household production; no additional adopted capabilities.</p>');
  if(d.kind==='language'){
    html+=section('Sound & structure',`<p>/${esc([...details.consonants,...details.vowels].join(' '))}/</p><p>${esc(details.phonotactics)}. ${esc(details.stress)}.</p>${pairs([['Word order',esc(details.grammar.word_order)],['Morphology',esc(details.grammar.morphology)],['Writing',details.writing.length?'Recorded convention':'No recorded script']])}`);
    html+=section('A small lexicon',`<table class="lexicon-table"><tbody>${Object.entries(details.lexicon).slice(0,16).map(([m,e])=>`<tr><td>${esc(m)}</td><td title="${esc(e.formation)}">${esc(e.form)}</td></tr>`).join('')}</tbody></table>`);
    html+=section('Lineage & contact',details.parents.length?`<p>Descends from ${details.parents.map(id=>`<button class="text-button" data-entity="language:${id}">${esc(state.data.languages[id]?.name||id)}</button>`).join(', ')}.</p>`:'<p>A founding variety. Shared words and traits can arrive through later contact.</p>');
    if(details.contact_sources.length)html+=`<p class="muted">${number(details.contact_sources.length)} recorded lexical loans; ${number(details.sound_rules.length)} regular sound changes.</p>`;
  }
  if(d.kind==='polity')html+=section('Institutions & capacity',pairs([['Effective provinces',number(details.territory.length)],['Administrative reach',`${Math.round(details.administrative_reach*100)}%`],['Legitimacy estimate',`${Math.round(details.legitimacy*100)}%`],['Treasury',number(details.treasury)],['Succession',esc(details.succession)]])+`<p>${esc(details.institutions.join(', '))}.</p>`);
  if(details.community_profiles){const profile=Object.values(details.community_profiles)[0];if(profile)html+=section('Life & disagreement',`<p>${esc(profile.shared_practice)}. Prestige can rest on ${esc(profile.prestige)}.</p><p>${esc(profile.contested_practice)} remains a contested practice. One minority position: ${esc(profile.minority_position.toLowerCase())}.</p>`);}
  html+=section('Recorded turning points',eventsHTML(d.events.slice(0,10)));content.innerHTML=html;
}

function renderCompare(){const content=$('dossier-content');const others=state.runs.filter(r=>r.id!==state.run);content.innerHTML=`<p class="entity-kind">Compare at ${esc(state.data.summary.date)}</p><h2 class="entity-title">Paths history took</h2><p class="entity-subtitle">Align two worlds or compare an intervention branch with its parent.</p><label for="compare-world">Compare with</label><select id="compare-world" class="comparison-select"><option value="">Choose a saved world</option>${others.map(r=>`<option value="${r.id}">World ${r.seed}${r.parent?' · branch':''} · ${labelYear(r.latest_year,r.start_year)}</option>`).join('')}</select><div id="comparison-result">${others.length?'':'<p class="muted">Generate a second world or branch a selected region to compare histories.</p>'}</div><p class="callout">Differences follow modeled scenarios. They are not identified causal effects.</p>`;const parent=state.data.summary.parent?.id;if(parent&&others.some(r=>r.id===parent)){ $('compare-world').value=parent;loadComparison(parent).catch(report);}}
async function loadComparison(other){
  if(!other)return;
  const otherInfo=state.runs.find(r=>r.id===other);
  const start=state.data.summary.start_year;
  const startDifference=(otherInfo.start_year+(otherInfo.start_year<0?1:0))-(start+(start<0?1:0));
  const year=Math.min(state.year,otherInfo.latest_year+startDifference);
  if(year<Math.max(0,startDifference)){
    $('comparison-result').innerHTML='<p class="muted">These worlds have no shared saved date through the selected year.</p>';
    return;
  }
  const result=await api(path('compare',{other,year}));
  if(!$('comparison-result'))return;
  const delta=result.population_delta;
  $('comparison-result').innerHTML=`<p class="muted">Aligned at ${labelYear(year,start)}</p><div class="comparison-change ${delta>=0?'positive':'negative'}">${delta>0?'+':''}${number(delta)} people</div><p class="muted">Comparison world minus the current world · ${(result.population_relative*100).toFixed(2)}%</p>${section('Outcomes',pairs([['Different borders',result.border_differences===null?'Different geography':number(result.border_differences)],['Living language difference',number(result.language_count_delta)],['Varieties with changed words',result.lexical_varieties_changed===null?'Different language catalogs':number(result.lexical_varieties_changed)],['Earliest recorded divergence',result.earliest_recorded_divergence===null?'None':labelYear(result.earliest_recorded_divergence,start)]]))}${section('First differing events',eventsHTML(result.divergence_events.left.slice(0,4)))}<p class="muted">For different seeds, only aggregate quantities are comparable; local borders are not aligned.</p>`;
}

async function showEvent(id){const event=await api(path('event',{id}));$('event-content').innerHTML=`<p class="entity-kind">${esc(human(event.type))} · ${labelYear(event.year,state.data.summary.start_year)}</p><p>${esc(event.text)}</p><p class="event-reference">${esc(event.id)}</p>${section('Conditions',`<pre>${esc(JSON.stringify(event.conditions,null,2))}</pre>`)}${section('Recorded changes',`<pre>${esc(JSON.stringify(event.deltas,null,2))}</pre>`)}${section('Rule & uncertainty',`<p>${esc(event.rule_id)} · version ${event.rule_version}</p><p>${esc(event.uncertainty)}</p>${event.draw===null?'':`<p>Random draw: ${event.draw.toFixed(6)}</p>`}`)}${section('Recorded inputs & triggers',event.parents.length?event.parents.map(parent=>`<button class="text-button event-parent" data-event="${esc(parent)}">${esc(parent)}</button>`).join(''):'<p>Initial conditions and this year’s draws supply the inputs.</p>')}${event.related_events?.length?section('Related history',`<p>Earlier records involving the same entities; these links do not assert causation.</p>${event.related_events.map(parent=>`<button class="text-button event-parent" data-event="${esc(parent)}">${esc(parent)}</button>`).join('')}`):''}`;if(!$('event-dialog').open)$('event-dialog').showModal();}
async function accounting(){const result=await api(path('ledger',{year:state.year}));if(!result.ledger){toast('This is the initial checkpoint, before annual accounting.');return;}const pid=state.selected.id,l=result.ledger;const deaths=Object.values(l.deaths).reduce((total,v)=>total+v[pid],0);$('event-content').innerHTML=`<h3>${esc(state.data.provinces[pid].name)} · ${esc(state.data.summary.date)}</h3>${section('Population identity',pairs([['Opening population',number(l.population_open[pid])],['Births',`+${number(l.births[pid])}`],['Deaths',`−${number(deaths)}`],['Immigration',`+${number(l.immigration[pid])}`],['Emigration',`−${number(l.emigration[pid])}`],['Closing population',number(l.population_close[pid])]]))}${section('Food stocks · consumption years',pairs([['Opening reserves',number(l.food_open[pid])],['Production',number(l.food_produced[pid])],['Imports',number(l.food_imports[pid])],['Exports',number(l.food_exports[pid])],['Consumption',number(l.food_consumed[pid])],['Closing reserves',number(l.food_close[pid])]]))}<p class="event-reference">Source: exact annual ledger, commit ${state.year}. Seed, spoilage and overflow are recorded in the export.</p>`;$('event-dialog').showModal();}
function showBranch(){if(!state.selected||state.selected.kind!=='province')return;if(!state.data.summary.can_simulate){toast('Generate a new world with this seed to use the revised population model.');return;}if(state.job.running){toast('Pause this world before creating a branch.');return;}const p=state.data.provinces[state.selected.id];$('branch-context').textContent=`Copy this history at ${state.data.summary.date} and change conditions around ${p.name} starting the following year.`;$('branch-dialog').showModal();}

function searchEntities(){const term=$('search').value.trim().toLowerCase();if(!term||!state.data){$('search-results').hidden=true;return;}const entities=[...state.data.provinces.map(p=>({kind:'province',id:p.id,name:p.display_name||p.name,description:`${number(p.population)} people · ${p.biome}`})),...Object.values(state.data.settlements||{}).map(s=>({kind:'settlement',id:s.id,name:s.name,description:s.city_founded===null?'Settlement':'City'})),...Object.values(state.data.languages).map(l=>({kind:'language',id:l.id,name:l.name,description:'Language variety'})),...Object.values(state.data.polities).map(p=>({kind:'polity',id:p.id,name:p.name,description:p.form}))];const matches=entities.filter(e=>e.name.toLowerCase().includes(term)||String(e.id)===term).slice(0,12);$('search-results').innerHTML=matches.length?matches.map(e=>`<button data-entity="${e.kind}:${e.id}">${esc(e.name)}<span>${esc(e.description)}</span></button>`).join(''):'<p class="muted" style="padding:12px">No matching entity at this date.</p>';$('search-results').hidden=false;}
async function pollJob(){if(!state.run)return;try{const run=state.run;const status=await api(`/api/job/${run}`);if(run!==state.run)return;const wasRunning=state.job.running;state.job=status;updateJob();if(status.running&&status.year!==state.data?.summary.latest_year){await refreshTimeline();await loadWorld(status.year);}else if(wasRunning&&!status.running){await refreshTimeline();await loadWorld();await loadRuns(state.run);if(status.error)toast(status.error.message);else toast(`Saved through ${state.data.summary.date}.`);}}catch(error){report(error);}}
function updateJob(){const active=!!state.job.running;$('run-label').textContent=active?'Pause':'Run';$('run-icon').textContent=active?'Ⅱ':'▶';$('job-status').hidden=!active;$('job-status').textContent=active?`Advancing: year ${number(state.job.year)} of ${number(state.job.target)}. Each committed year is saved.`:'';}

function attachHandlers(){
  $('run-select').addEventListener('change',()=>selectRun($('run-select').value).catch(report));
  for(const id of ['new-world','empty-generate'])$(id).addEventListener('click',()=>$('generate-dialog').showModal());
  document.querySelectorAll('.close-dialog').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
  document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}}));
  $('random-seed').addEventListener('click',()=>{$('seed').value=crypto.getRandomValues(new Uint32Array(1))[0];});
  $('preset').addEventListener('change',()=>{$('preset-note').textContent=({'balanced':'Unscripted histories on an Earth-like world.','river-corridor':'Wetter basins and more productive river land.','modern-capable':'Faster experimentation. A modern endpoint still does not guarantee industry.'})[$('preset').value];});
  $('generate-form').addEventListener('submit',async event=>{event.preventDefault();const button=$('generate-submit');button.disabled=true;button.textContent='Generating…';try{const result=await api('/api/generate',{seed:Number($('seed').value),provinces:Number($('provinces').value),preset:$('preset').value,start_year:Number($('start-year').value)});$('generate-dialog').close();state.run=null;await loadRuns(result.id);toast('World generated. Run the timeline to begin its history.');}catch(error){report(error);}finally{button.disabled=false;button.textContent='Generate world';}});
  $('run').addEventListener('click',async()=>{if(!state.run)return;try{if(state.job.running){await api(path('pause'),{});toast('Pausing after the current annual commit.');}else{state.job=await api(path('simulate'),{years:Number($('advance-years').value)});updateJob();}}catch(error){report(error);}});
  $('year').addEventListener('input',()=>{const year=Number($('year').value);$('view-year').textContent=labelYear(year,state.data.summary.start_year);clearTimeout(scrubTimer);scrubTimer=setTimeout(()=>loadWorld(year).catch(report),130);});
  $('latest-year').addEventListener('click',()=>loadWorld().catch(report));
  $('timeline-chart').addEventListener('click',event=>{if(!state.data)return;const r=$('timeline-chart').getBoundingClientRect();const year=Math.round((event.clientX-r.left)/r.width*state.data.summary.latest_year);loadWorld(year).catch(report);});
  $('search').addEventListener('input',searchEntities);
  $('search').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();$('search-results').querySelector('button')?.click();}if(event.key==='Escape')$('search-results').hidden=true;});
  document.addEventListener('click',event=>{const entity=event.target.closest('[data-entity]');if(entity){const [kind,id]=entity.dataset.entity.split(':');selectEntity(kind,id).catch(report);}const recorded=event.target.closest('[data-event]');if(recorded)showEvent(recorded.dataset.event).catch(report);if(event.target.id==='branch-here')showBranch();if(event.target.id==='show-accounting')accounting().catch(report);});
  for(const tab of ['inspect','history','compare'])$(`${tab}-tab`).addEventListener('click',()=>{state.tab=tab;updateTabs();renderPanel().catch(report);});
  $('dossier-content').addEventListener('change',event=>{if(event.target.id==='compare-world')loadComparison(event.target.value).catch(report);if(event.target.id==='history-type'){state.historyType=event.target.value;renderPanel().catch(report);}});
  $('branch-form').addEventListener('submit',async event=>{event.preventDefault();const button=event.target.querySelector('[type=submit]');button.disabled=true;try{const result=await api(path('branch'),{year:state.year,province:state.selected.id,kind:$('intervention-kind').value,factor:Number($('intervention-factor').value)});$('branch-dialog').close();state.run=null;await loadRuns(result.id);toast('Branch saved. Advance its timeline to explore the intervention.');}catch(error){report(error);}finally{button.disabled=false;}});
  $('export').addEventListener('click',async()=>{const button=$('export');button.disabled=true;button.textContent='Exporting…';try{const result=await api(path('export'),{year:state.year});const a=document.createElement('a');a.href=result.download;a.download='world-history.zip';document.body.append(a);a.click();a.remove();toast('Export ready: map, tables, manifest and event-cited history.');}catch(error){report(error);}finally{button.disabled=false;button.textContent='Export';}});
  for(const id of ['about','model-details'])$(id).addEventListener('click',()=>{const g=state.data?.geography;$('geography-report').innerHTML=g?section('This geography',pairs([['Land area',`${number(g.land_area_km2)} km²`],['Drainage basins',number(g.basins)],['Arable share',`${(g.arable_share*100).toFixed(1)}%`],['Rejected attempts',number(g.rejected_attempts)]])+`<p>${esc(g.limitations)}</p>`):'';$('model-dialog').showModal();});
  for(const [id,factor] of [['zoom-in',1.35],['zoom-out',1/1.35]])$(id).addEventListener('click',()=>{state.zoom=Math.max(1,Math.min(8,state.zoom*factor));drawMap();});
  $('reset-map').addEventListener('click',()=>{state.zoom=1;state.pan={x:0,y:0};drawMap();});
  $('map').addEventListener('wheel',event=>{event.preventDefault();state.zoom=Math.max(1,Math.min(8,state.zoom*(event.deltaY<0?1.15:1/1.15)));drawMap();},{passive:false});
  $('map').addEventListener('pointerdown',event=>{dragging={x:event.clientX,y:event.clientY,pan:{...state.pan}};moved=false;$('map').setPointerCapture(event.pointerId);});
  $('map').addEventListener('pointermove',event=>{if(dragging&&state.zoom>1){const dx=event.clientX-dragging.x,dy=event.clientY-dragging.y;if(Math.abs(dx)+Math.abs(dy)>5)moved=true;if(moved){state.pan={x:dragging.pan.x+dx,y:dragging.pan.y+dy};drawMap();}}const p=hitMap(event.clientX,event.clientY);const tooltip=$('tooltip');tooltip.hidden=!p||moved;if(p&&!moved){tooltip.innerHTML=`${esc(p.name)}<small>${number(p.population)} people · ${esc(p.biome)}</small>`;const rect=$('map-wrap').getBoundingClientRect();tooltip.style.left=Math.min(event.clientX-rect.left+12,rect.width-200)+'px';tooltip.style.top=Math.max(65,event.clientY-rect.top-45)+'px';}});
  $('map').addEventListener('pointerup',event=>{if(!moved){const p=hitMap(event.clientX,event.clientY);if(p)selectEntity('province',p.id).catch(report);}dragging=null;moved=false;});
  $('map').addEventListener('pointercancel',()=>{dragging=null;moved=false;});
  $('map').addEventListener('pointerleave',()=>$('tooltip').hidden=true);
  new ResizeObserver(()=>{drawMap();drawTimeline();}).observe($('map-wrap'));
}

initLayers();attachHandlers();loadRuns().catch(report);setInterval(pollJob,1500);
