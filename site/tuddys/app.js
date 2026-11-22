/* TUDDYS — original NHL True Blender deck presentation adapted to NFL.
   Read-only. No player selection, odds ranking, fake gate PASSes, or inferred official confirmation. */
"use strict";
const ET="America/New_York";
const $=id=>document.getElementById(id);
const mk=(tag,cls,value)=>{
  const node=document.createElement(tag);if(cls)node.className=cls;
  if(value!==null&&value!==undefined)node.textContent=String(value);
  return node;
};
const num=v=>typeof v==="number"&&Number.isFinite(v)?new Intl.NumberFormat("en-US").format(v):"—";
const dateText=s=>{
  if(!/^\d{4}-\d{2}-\d{2}$/.test(String(s||"")))return "No saved slate";
  return new Intl.DateTimeFormat("en-US",{month:"short",day:"numeric",year:"numeric",timeZone:"UTC"})
    .format(new Date(s+"T12:00:00Z"));
};
const timeText=s=>{
  const d=new Date(String(s||""));return Number.isNaN(d.getTime())?"Time unverified":
    new Intl.DateTimeFormat("en-US",{timeZone:ET,month:"short",day:"numeric",hour:"numeric",minute:"2-digit",timeZoneName:"short"}).format(d);
};
const etToday=()=>{
  const ps=new Intl.DateTimeFormat("en-US",{timeZone:ET,year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(new Date());
  const d=Object.fromEntries(ps.map(p=>[p.type,p.value]));return [d.year,d.month,d.day].join("-");
};
const state={latest:null,archive:[],date:null,flipped:null,flippedPool:null,requestId:0,selected:null};
const sourceUrl="https://github.com/benhavinsports/tuddys/blob/main/runs/latest.json";
const escapeHtml=s=>String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
async function getJson(path){const url=new URL(path,location.href);url.searchParams.set("_",String(Date.now()));const r=await fetch(url,{cache:"no-store"});if(!r.ok)throw Error("HTTP "+r.status);return r.json();}
const current=()=>state.archive.find(x=>x.date===state.date)||null;
const isLatest=()=>state.latest?.date===state.date;
const players=()=>current()?.players||[];
function readCurrentStatus(){
  const c=current(), l=isLatest()?state.latest:null;
  $("hero-date").textContent=dateText(state.date||l?.date);
  $("hero-phase").textContent=c?(c.stage||"PROJECTED")+" · "+(state.date===etToday()?"TODAY":"SAVED SLATE"):"NO CORE SAVED";
  $("hero-sync").textContent=l?.runUTC?"Scanned "+timeText(l.runUTC):"Latest scan not available";
  const notice=$("slate-notice");notice.replaceChildren();
  if(c?.players?.length){
    const badge=mk("span","pill "+(state.date===etToday()?"neutral":"warning"),
      (c.stage||"PROJECTED")+" · "+c.players.length+" SAVED");
    notice.appendChild(badge);
    if(!l?.fullCertification){
      const warning=mk("span","nfl-review-note","RESEARCH CARD · NOT FULLY CERTIFIED");
      notice.appendChild(warning);
    }
  }else{
    notice.appendChild(mk("span","pill warning","AWAITING SAVED CARD"));
  }
}
function renderPicker(){
  const picker=$("slate-select");picker.replaceChildren();
  const all=[...new Set(state.archive.map(x=>x.date).filter(Boolean))].sort().reverse();
  if(!all.length){picker.appendChild(mk("option","","No saved slates"));picker.disabled=true;return;}
  for(const date of all){const e=state.archive.find(x=>x.date===date);const o=mk("option","",date+" · "+(e?.players?.length||0)+"-LEG CORE");o.value=date;picker.appendChild(o);}
  picker.value=state.date||all[0];picker.disabled=false;
}
function cardPhoto(player,team){
  const art=mk("div","card-illustration collector-art nfl-collector-art");
  art.appendChild(mk("span","collector-foil-rings"));
  const ball=mk("div","nfl-football-symbol");ball.setAttribute("aria-hidden","true");
  ball.innerHTML='<svg viewBox="0 0 280 280" xmlns="http://www.w3.org/2000/svg"><g transform="translate(140 140) rotate(-37)"><ellipse rx="65" ry="113" fill="#d3ad76" stroke="#ffe2a0" stroke-width="3"/><path d="M-56 -58 Q0 -73 56 -58 M-56 58 Q0 73 56 58" fill="none" stroke="#5b402b" stroke-width="8"/><path d="M0 -43 V43 M-16 -25 H16 M-16 -8 H16 M-16 9 H16 M-16 26 H16" stroke="#5b402b" stroke-width="6" stroke-linecap="round"/></g></svg>';
  art.appendChild(ball);
  const tag=mk("span","nfl-art-team",team||"NFL");art.appendChild(tag);
  const shade=mk("span","collector-photo-shade");shade.setAttribute("aria-hidden","true");art.appendChild(shade);
  const ini=mk("span","collector-fallback",String(player||"").split(/\s+/).map(x=>x[0]).join("").slice(0,2).toUpperCase());
  ini.setAttribute("aria-hidden","true");art.appendChild(ini);
  return art;
}
function situationLabel(s){return String(s||"").toLowerCase().replace(/_/g," ");}
function makeReport(p,stage,close){
  const report=mk("section","nfl-scout-report scout-report");const head=mk("div","nfl-report-head");
  head.appendChild(mk("span","nfl-report-kicker","TUDDYS / SCOUTING RECEIPT"));
  const back=mk("button","nfl-report-close","✕ CLOSE");
  back.type="button";back.setAttribute("aria-label","Close scouting report");back.addEventListener("click",close);
  head.appendChild(back);report.appendChild(head);
  report.appendChild(mk("h3","nfl-report-name",p.name||"Game survivor"));
  report.appendChild(mk("div","nfl-report-match",p.game?p.game:((p.team||"—")+" vs "+(p.opponent||"—"))));
  const summary=mk("div","nfl-report-summary");
  const rows=[
    [num(p.directTDs),"CREDITED SEASON TDs"],
    [num(p.redZoneActions),"RED-ZONE ACTIONS"],
    [Array.isArray(p.matchedSituations)?num(p.matchedSituations.length):"—","MATCHED SCORING LANES"],
    [num(p.ownedActions),"OWNED ACTIONS"],
  ];
  for(const [v,label] of rows){const item=mk("div","nfl-report-stat");item.appendChild(mk("strong","",v));item.appendChild(mk("span","",label));summary.appendChild(item)}
  report.appendChild(summary);
  const situations=Array.isArray(p.matchedSituations)?p.matchedSituations:[];
  if(situations.length){
    report.appendChild(mk("h4","nfl-report-section","PHYSICAL TD ROUTES / 17 ALIGNMENTS"));
    const laneList=mk("div","nfl-lane-list");
    for(const name of situations){
      const s=p.scoringSituations?.[name]||{};
      const row=mk("div","nfl-lane");
      row.appendChild(mk("strong","",situationLabel(name)));
      row.appendChild(mk("span","","Own "+num(s.ownedActions)+" actions · opponent "+num(s.defenseTouchdownsAllowed)+" TDs allowed"));
      laneList.appendChild(row);
    }
    report.appendChild(laneList);
  }else{
    report.appendChild(mk("p","nfl-report-empty","Player-level scouting receipts for this game were not included in this saved export. No gate is being shown as passed without proof."));
  }
  report.appendChild(mk("p","nfl-report-disclaimer",
    "Original G0–G18 / overlay run is not yet independently certified across all NFL evidence sources. This is saved research, not a guaranteed TD or verified game-day active designation."));
  const sources=mk("a","nfl-report-source","OPEN CANONICAL ENGINE REPORT ↗");
  sources.href=sourceUrl;sources.target="_blank";sources.rel="noopener noreferrer";report.appendChild(sources);
  return report;
}
function toggleCore(key){
  state.flipped=state.flipped===key?null:key;
  document.body.classList.toggle("core-report-open",Boolean(state.flipped));
  for(const item of document.querySelectorAll("#core-cards .core-card")){
    const active=item.dataset.leg===state.flipped;
    item.classList.toggle("is-flipped",active);item.setAttribute("aria-expanded",String(active));
  }
}
function coreCard(p,i,total){
  const key=String(p.gameId)+":"+String(p.playerId);
  const card=mk("article","core-card path-primary nfl-core-card");
  card.dataset.leg=key;card.tabIndex=0;card.setAttribute("role","button");
  card.setAttribute("aria-label","Flip touchdown scouting card for "+p.name);
  card.setAttribute("aria-expanded",String(state.flipped===key));
  if(state.flipped===key)card.classList.add("is-flipped");
  const inner=mk("div","card-flip-inner"),front=mk("div","card-face card-front");
  const mast=mk("div","card-head collector-masthead");
  mast.appendChild(mk("span","card-index","TRUE BLENDER / NFL"));
  mast.appendChild(mk("span","collector-series","PREMIER · "+String(i+1).padStart(2,"0")+"/"+String(total).padStart(2,"0")));
  front.appendChild(mast);front.appendChild(cardPhoto(p.name,p.team));
  const plate=mk("div","card-nameplate collector-nameplate");
  const names=String(p.name||"UNKNOWN PLAYER").trim().split(/\s+/),family=names.pop();
  plate.appendChild(mk("span","collector-given",names.join(" ").toUpperCase()));
  plate.appendChild(mk("strong","player-name",family.toUpperCase()));
  plate.appendChild(mk("span","collector-team-line",(p.team||"NFL")+" · "+(p.team||"—")+" VS "+(p.opponent||"—")));
  const row=mk("div","collector-path-row");
  row.appendChild(mk("span","pill path-primary","ANYTIME TD"));
  row.appendChild(mk("span","collector-origin","OWN SCORING ROUTE"));
  plate.appendChild(row);
  plate.appendChild(mk("span","collector-stats",num(p.directTDs)+" credited TDs · "+num(p.redZoneActions)+" red-zone actions"));
  front.appendChild(plate);
  const bottom=mk("div","card-bottom collector-flip-line");
  bottom.appendChild(mk("span","","FLIP FOR SCOUTING EVIDENCE"));bottom.appendChild(mk("span","tiny-arrow","↗"));front.appendChild(bottom);
  const rear=mk("div","card-face card-back");
  rear.appendChild(makeReport(p,current()?.stage||"PROJECTED",()=>toggleCore(key)));
  inner.appendChild(front);inner.appendChild(rear);card.appendChild(inner);
  card.addEventListener("click",e=>{if(e.target.closest("a,button,summary,details,.nfl-scout-report"))return;toggleCore(key)});
  card.addEventListener("keydown",e=>{if(e.target!==card)return;if(e.key==="Enter"||e.key===" "){e.preventDefault();toggleCore(key)}});
  return card;
}
function renderCore(){
  const holder=$("core-cards");holder.replaceChildren();
  const ps=players();
  if(!ps.length){holder.appendChild(mk("div","empty-state","No authoritative Core saved for the selected NFL slate."));return}
  for(const [i,p] of ps.entries())holder.appendChild(coreCard(p,i,ps.length));
}
function togglePool(key){
  state.flippedPool=state.flippedPool===key?null:key;
  document.body.classList.toggle("pool-card-open",Boolean(state.flippedPool));
  for(const item of document.querySelectorAll("#pool-list .pool-flip-card")){
    const active=item.dataset.cardKey===state.flippedPool;item.classList.toggle("is-flipped",active);
    item.dataset.facing=active?"back":"front";
    const button=item.querySelector(".pool-front-turn");
    if(button)button.setAttribute("aria-expanded",String(active));
  }
}
function renderPool(){
  const holder=$("pool-list");holder.replaceChildren();
  const games=isLatest()?state.latest?.gameSurvivors||[]:[];
  if(!games.length){holder.appendChild(mk("div","empty-state","No saved per-game survivors published for this slate."));return}
  const ps=players(),coreIds=new Set(ps.map(p=>p.gameId));
  const stats=mk("div","pool-stat-strip");
  for(const [v,label] of [[games.length+" / "+(state.latest?.slateGames||games.length),"GAMES REVIEWED"],[ps.length,"CORE SAVED"],[state.latest?.playerPoolCount||"—","PLAYERS SCANNED"]]){
    const d=mk("div","pool-stat");d.appendChild(mk("strong","",v));d.appendChild(mk("span","",label));stats.appendChild(d);
  }
  holder.appendChild(stats);
  for(const g of games){
    const key=String(g.gameId),active=state.flippedPool===key;
    const p=ps.find(p=>p.gameId===key)||null;
    const gameName=String(g.game||"NFL MATCHUP").replace(/@/g," @ ");
    const card=mk("article","pool-flip-card pool-collector-card qualified"+(p?" core-pool-card":"")+(active?" is-flipped":""));
    card.dataset.cardKey=key;card.dataset.facing=active?"back":"front";
    const inner=mk("div","pool-flip-inner"),front=mk("div","pool-face pool-front");
    const turn=mk("button","pool-front-turn");turn.type="button";
    turn.setAttribute("aria-expanded",String(active));
    turn.setAttribute("aria-label","Flip game survivor card for "+gameName);
    turn.appendChild(cardPhoto(g.survivor, p?.team||gameName.split(" @ ")[1]));
    const head=mk("div","pool-card-head collector-pool-masthead");
    head.appendChild(mk("span","pool-matchup",gameName));
    head.appendChild(mk("span","pool-card-series",p?"CORE MEMBER":"NFL · GAME SURVIVOR"));turn.appendChild(head);
    const plate=mk("div","pool-card-player collector-pool-nameplate");
    plate.appendChild(mk("span","pool-team",p?.team||"TRUE BLENDER NFL"));
    plate.appendChild(mk("strong","pool-player-name",g.survivor||"NO SURVIVOR SAVED"));
    const route=mk("div","pool-route");
    route.appendChild(mk("span","pool-path primary",p?"CORE MEMBER":"GAME SURVIVOR"));
    plate.appendChild(route);
    plate.appendChild(mk("span","pool-short-proof",num(g.playerPoolEvidenceCandidates)+" candidates · saved engine result"));
    turn.appendChild(plate);
    turn.appendChild(mk("span","pool-turn-tip","FLIP · GAME SCOUTING REPORT   ↗"));
    turn.addEventListener("click",()=>togglePool(key));front.appendChild(turn);
    const back=mk("div","pool-face pool-back");
    back.appendChild(makeReport(p||{name:g.survivor,game:gameName},state.latest?.stage||"PROJECTED",()=>togglePool(key)));
    inner.appendChild(front);inner.appendChild(back);card.appendChild(inner);holder.appendChild(card);
  }
}
function render(){
  renderPicker();readCurrentStatus();renderCore();renderPool();
  const c=players().length;
  const aside=document.querySelector(".core-section .deck-aside");
  if(aside)aside.textContent=c===2?"TWO GAMES · ONE CARD":"THREE GAMES · ONE CARD";
}
function chooseDate(date){
  state.date=date;state.flipped=null;state.flippedPool=null;
  document.body.classList.remove("core-report-open","pool-card-open");render();
  try{const url=new URL(location.href);url.searchParams.set("slate",date);history.replaceState(null,"",url)}catch(_){}
}
function ingest(latest,archive){
  state.latest=latest;
  state.archive=(archive.cards||[]).filter(c=>c&&Array.isArray(c.players)&&c.date);
  const dates=state.archive.map(c=>c.date).sort().reverse();
  const requested=new URL(location.href).searchParams.get("slate");
  const d=dates.includes(requested)?requested:
    (state.date&&dates.includes(state.date)?state.date:
      dates.includes(etToday())?etToday():dates[0]||null);
  state.date=d;render();
}
let signature=null;
async function fetchState(){
  const [latest,archive]=await Promise.all([getJson("./data/latest.json"),getJson("./data/cards-archive.json")]);
  const next=JSON.stringify({runUTC:latest.runUTC,stage:latest.stage,card:latest.authoritativeCore?.map(p=>p.playerId),archive:archive.cards?.map(x=>[x.date,x.stage,x.players?.map(p=>p.playerId)])});
  if(next!==signature){signature=next;ingest(latest,archive)}
}
function boot(){
  $("refresh").addEventListener("click",()=>fetchState().catch(err=>$("hero-sync").textContent="Refresh error: "+err.message));
  $("slate-select").addEventListener("change",e=>chooseDate(e.target.value));
  const nav=[...document.querySelectorAll(".main-nav a[data-nav]")];
  for(const link of nav)link.addEventListener("click",()=>{
    for(const other of nav)other.removeAttribute("aria-current");
    link.setAttribute("aria-current","page");
  });
  fetchState().catch(err=>{
    $("hero-phase").textContent="SAVED FEED NOT AVAILABLE";
    $("core-cards").replaceChildren(mk("div","empty-state","Dashboard data could not be verified: "+err.message));
    $("pool-list").replaceChildren(mk("div","empty-state","The site does not invent touchdown cards when publication is unavailable."));
  });
  window.setInterval(()=>{if(!document.hidden)fetchState().catch(()=>{})},120000);
}
document.addEventListener("keydown",e=>{
  if(e.key!=="Escape")return;
  if(state.flipped)toggleCore(state.flipped);
  if(state.flippedPool)togglePool(state.flippedPool);
});
boot();
