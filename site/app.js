/* TRUE BLENDER — read-only mobile-first dashboard.
   No scorer picks, path quotas, client-side gate PASSes or live data guesses.
   Card identities and source evidence come ONLY from GitHub Actions exports. */
"use strict";
const ET="America/New_York";
const MASTER=[...Array(11)].map((_,i)=>"G"+i).concat("G10.5",
  ...[...Array(8)].map((_,i)=>"G"+(i+11)));
const OVERLAY=[...Array(11)].map((_,i)=>"Step"+i).concat("Step10.5",
  ...[...Array(4)].map((_,i)=>"Step"+(i+11)));
const EXPLAIN={
 G0:"Goalie target & attacking direction",
 G1:"Venue, rest & travel",
 G2:"Full eligible skater pool",
 G3:"Measured goalie vulnerability",
 G4:"Own shot-origin mechanism",
 G5:"Own route against goalie weakness",
 G6:"Even-strength & power-play deployment",
 G7:"Dated recent-goal recurrence",
 G8:"Game context & route conditions",
 G9:"Opponent defensive coverage",
 G10:"Direct goal-credit ownership",
 "G10.5":"Mandatory teammate recipient separation",
 G11:"Recent individual shot pressure",
 G12:"Official scoring-log reconciliation",
 G13:"Qualitative numerology & milestones",
 G14:"Evidence for exceptional scoring route",
 G15:"Independent finish mechanism",
 G16:"Full teammate / depth comparison",
 G17:"Contradiction and counterevidence review",
 G18:"Certified selection and scoring path",
 Step0:"Goalie-first attack side",
 Step1:"Full active-roster scan",
 Step2:"Venue, rest & travel context",
 Step3:"Goalie vulnerability / defender avoid",
 Step4:"Dated goal frequency & recurrence",
 Step5:"Own shot mechanism & sample",
 Step6:"EV, PP & PK deployment",
 Step7:"Pre-selection archetype tagging",
 Step8:"Observed defensive shift coverage",
 Step9:"Recent shot pressure and continuity",
 Step10:"Direct measured goalie target",
 "Step10.5":"Direct challenger separation",
 Step11:"Unusual or WHO-route review",
 Step12:"Depth and rival comparison",
 Step13:"Qualitative number/date/milestone",
 Step14:"Final source contradiction review",
};
const state={
 latest:null,archive:[],selectedDate:null,selectedLeg:null,
 gateFilter:"all",gateData:null,gateLoadError:null,requestId:0,flippedLeg:null,
};
const $=id=>document.getElementById(id);
const el=(tag,className,textValue)=>{
 const node=document.createElement(tag);
 if(className)node.className=className;
 if(textValue!==undefined&&textValue!==null)node.textContent=String(textValue);
 return node;
};
const number=v=>typeof v==="number"&&Number.isFinite(v)?v:"—";
const unique=values=>[...new Set((values||[]).filter(Boolean))];
function etDate(iso){
 if(!iso)return "—";
 const d=new Date(iso);
 if(Number.isNaN(d.getTime()))return String(iso);
 return new Intl.DateTimeFormat("en-US",{timeZone:ET,month:"short",day:"numeric",
   year:"numeric"}).format(d);
}
function etTime(iso){
 if(!iso)return "Time unverified";
 const d=new Date(iso);
 if(Number.isNaN(d.getTime()))return "Time unverified";
 return new Intl.DateTimeFormat("en-US",{timeZone:ET,hour:"numeric",minute:"2-digit",
   timeZoneName:"short"}).format(d);
}
function etToday(){
 const parts=new Intl.DateTimeFormat("en-US",{timeZone:ET,year:"numeric",
    month:"2-digit",day:"2-digit"}).formatToParts(new Date());
 const v=Object.fromEntries(parts.map(p=>[p.type,p.value]));
 return v.year+"-"+v.month+"-"+v.day;
}
async function json(path){
 const res=await fetch(path+(path.includes("?")?"&":"?")+"t="+Date.now(),{cache:"no-store"});
 if(!res.ok)throw Error("Source file unavailable ("+res.status+")");
 return await res.json();
}
// Read-only public mirror of the Goals engine's saved G18 Core.
// A public dashboard may display verified evidence but never chooses skaters.
// Exact selected-player receipt subset from the saved private G18 run.
function verifiedMirroredGateExcerpt(exported){
 const legs=exported?.card?.current_legs||[];
 const pages=exported?.selectedGateEvidence;
 if(!Array.isArray(pages)||pages.length!==legs.length||!legs.length)return null;
 const originals=new Set();
 for(const leg of legs){
  const page=pages.find(x=>String(x.gameId)===String(leg.gameId)&&
    String(x.playerId)===String(leg.playerId));
  if(!page||!Array.isArray(page.gateDetails)||
     page.gateDetails.length!==MASTER.length||page.selectedOriginalGateReceiptsComplete!==true)return null;
  const key=String(page.gameId)+":"+String(page.playerId);
  if(originals.has(key))return null;
  originals.add(key);
  let overlays=0;
  for(let i=0;i<MASTER.length;i++){
   const row=page.gateDetails[i];
   if(row?.gate!==MASTER[i]||row.status!=="PASS"||
      row.prePuckRecord!==true||!Array.isArray(row.sourceIds)||
      !row.evidence||typeof row.evidence!=="object"||
      !Array.isArray(row.originalFunctions))return null;
   if(!["G8","G13"].includes(row.gate)&&
      !row.sourceIds.some(s=>typeof s==="string"&&s.startsWith("https://")))return null;
   overlays+=row.originalFunctions.filter(f=>f.status==="PASS").length;
  }
  if(overlays!==16)return null;
 }
 return pages;
}

function mergePublicGoalsCore(latest,archive,exported){
 const cards=Array.isArray(archive)?archive:[];
 const card=exported?.card;
 const legs=card?.current_legs;
 if(!exported||exported.verified!==true||
    !["G18_SOURCE_VERIFIED","FROZEN_GRADED"].includes(exported.cardStatus)||
    exported.sourceRepo!=="benhavinsports/Goals"||
    exported.selectedCoreFullyCertified!==true||
    exported.selectedMasterGatesAllPass!==true||
    exported.selectedOverlayGatesAllPass!==true||
    (exported.selectedSourceAttributionGaps||[]).length!==0||
    (exported.selectedExecutionOrderGaps||[]).length!==0||
    !exported.date||!card||!card.cardId||
    typeof card.fingerprint!=="string"||card.fingerprint.length!==64||
    card.fingerprint!==exported.statusFingerprint||
    !Array.isArray(legs)||![2,3].includes(legs.length)||
    legs.some(leg=>!leg.gameId||!leg.playerId||
       !["PRIMARY","TRANSFER","WHO"].includes(leg.path))||
    new Set(legs.map(leg=>String(leg.gameId))).size!==legs.length||
    (latest?.date&&latest.date>exported.date))return {latest,archive:cards};
 const proof=verifiedMirroredGateExcerpt(exported);
 const entry={
    date:exported.date,cardId:card.cardId,stage:exported.stage,
    verified:true,fingerprint:card.fingerprint,revision:card.revision,
    current_legs:legs,cardStatus:exported.cardStatus,
    grade:exported.postgameGrade||null,
    hasGateEvidence:!!proof,
    gateEvidenceError:"The selected-player source receipts are not fully mirrored. Missing evidence is not presented as verified."
 };
 const rebuilt=[entry,...cards.filter(x=>x.date!==entry.date)]
    .sort((a,b)=>String(b.date).localeCompare(String(a.date)));
 const published={
    date:exported.date,stage:exported.stage,
    verified:true,card,postgameGrade:exported.postgameGrade||null,
    gameSurvivorPool:exported.gameSurvivorPool||[],
    gameSurvivorGateReceipts:proof?Object.fromEntries(proof.map(x=>[
      String(x.gameId)+":"+String(x.playerId),x.gateDetails
    ])):{},
    selectedGateEvidence:proof,
    savedOriginalGateEvidenceVerified:!!proof,
    originalSourceExcerptCondensed:exported.selectedGateEvidenceRepresentation||
      "ORIGINAL_SOURCE_EXCERPT",
    publicationDecision:"G18_SOURCE_VERIFIED_PUBLIC_MIRROR",
    survivorOnlyCertification:true,currentRunFullyCertified:false,
    gateCertification:{
      selectedMasterGatesAllPass:true,selectedOverlayGatesAllPass:true,
      selectedSourceAttributionGaps:[],selectedExecutionOrderGaps:[]
    },
    sourceActionUrl:exported.sourceActionUrl,
    publicProjectionOnly:true
 };
 return {latest:published,archive:rebuilt};
}

function pill(text,cls="neutral"){
 const span=el("span","pill "+cls,text);
 return span;
}
function statusClass(status){
 if(status==="PASS"||status==="CONFIRMED"||status==="WIN"||status==="HIT")return "success";
 if(["ELIMINATED","FAIL","LOSS","MISS"].includes(status))return "danger";
 if(status==="PROJECTED"||status==="EXPECTED"||status==="MIXED"||
    status==="NOT_EXECUTED"||status==="NO_PREPUCK_RECEIPT")return "warning";
 return "neutral";
}
function pathClass(path){
 return path==="PRIMARY"?"path-primary":path==="TRANSFER"?"path-transfer":
   path==="WHO"?"path-who":"neutral";
}
function link(url,custom){
 if(typeof url!=="string"||!url.startsWith("https://"))return null;
 try{
   const parsed=new URL(url);
   if(parsed.protocol!=="https:")return null;
   const a=el("a","",custom||parsed.hostname+" · view evidence");
   a.href=parsed.href;a.target="_blank";a.rel="noopener noreferrer";
   return a;
 }catch(_){return null;}
}
function countSelected(){
 const e=selectedEntry();
 return e&&e.current_legs?e.current_legs.length:0;
}
function selectedEntry(){
 const date=state.selectedDate;
 if(!date)return null;
 const saved=state.archive.find(x=>x.date===date);
 if(saved)return saved;
 const x=state.latest;
 if(x&&x.date===date&&x.card&&x.verified===true)return{
   date,cardId:x.card.cardId,stage:x.stage,verified:true,
   fingerprint:x.card.fingerprint,revision:x.card.revision,
   current_legs:x.card.current_legs||[],grade:x.postgameGrade||null,
   hasGateEvidence:!!state.gateData
 };
 return null;
}
function isLatest(){
 return state.latest&&state.latest.date===state.selectedDate;
}
function currentStatus(){
 const saved=selectedEntry();
 const recent=isLatest()?state.latest:{};
 return {
  date:state.selectedDate,
  phase:saved?.stage||recent?.stage||"UNVERIFIED",
  current:isLatest(),
  today:state.selectedDate===etToday(),
  audit:isLatest()?recent?.gateCertification||{}:{},
  verified:saved?.verified===true,
  certified:isLatest()?recent?.survivorOnlyCertification===true:
    saved?.verified===true,
 };
}
function auditedPath(leg){
 const saved=selectedEntry();
 const frozen=leg.path;
 const audit=isLatest()?(state.latest?.pathAudit||[]).find(x=>
   String(x.gameId)===String(leg.gameId)&&String(x.playerId)===String(leg.playerId)):null;
 if(!audit||audit.originalLockedPath!==frozen||audit.sameLockedRecipient!==true
    ||audit.doesNotReplaceCard!==true||!["PRIMARY","TRANSFER","WHO"].includes(audit.auditedPath)
    ||!Array.isArray(audit.sourceUrls)||!audit.sourceUrls.some(u=>String(u).startsWith("https://")))
    return {display:frozen,original:frozen,review:null};
 // The deployed source already checks audit timestamp against puck drop,
 // but recheck to avoid presenting a later classification as an original path.
 const observed=new Date(audit.reviewedAtUTC);
 const puck=new Date(leg.startUTC);
 if(!Number.isNaN(observed.getTime())&&!Number.isNaN(puck.getTime())
     &&observed>=puck)
     return {display:frozen,original:frozen,review:null};
 return {display:audit.auditedPath,original:frozen,review:audit};
}
function setText(id,value){
 const node=$(id);if(node)node.textContent=value;
}
function renderHeader(){
 const s=currentStatus(),saved=selectedEntry();
 const date=s.date||etToday();
 setText("hero-date",etDate(date+"T12:00:00Z"));
 setText("hero-phase",saved?s.phase+(s.today?" · today":" · archived"):
    s.today?"TODAY · AWAITING CARD":"LATEST SLATE · NO CORE");
 setText("hero-sync",state.latest?.publishedAt?"Published "+etTime(state.latest.publishedAt):
    "Publication not available");
 const count=countSelected();
 setText("stat-legs",count?String(count):"—");
 setText("stat-phase",saved?s.phase:"AWAITING");
 const valid=state.gateData?.legs?.every(x=>x.masterPassed===x.totalMaster
     &&x.overlayPassed===x.totalOverlay);
 setText("stat-gates",valid?"20 / 20":saved&&state.gateData?"REVIEW":"—");
 const recent=state.latest;
 setText("stat-scanned",s.current?
    number(recent?.selectionFunnel?.surveyedEligibleSkaters||
      recent?.eligibleSkaterRows):"—");
 const notice=$("slate-notice");
 notice.replaceChildren();
 if(saved?.unrestricted){notice.appendChild(pill(saved.verified?"UNRESTRICTED · VERIFIED":"UNRESTRICTED · LOCK UNVERIFIED",saved.verified?"":"warning"));}else if(!s.today&&saved){
   notice.appendChild(pill("ARCHIVED · "+date,"warning"));
   notice.appendChild(el("p","","This is a previously locked slate, not a new pick for today. Select a different date to inspect another card."));
 }else if(saved){
   const storedProof=s.current&&state.latest?.savedOriginalGateEvidenceVerified===true;
   const currentIncomplete=s.current&&state.latest?.currentRunFullyCertified!==true;
   notice.appendChild(pill(storedProof&&currentIncomplete?
     "SAVED CORE · SOURCE RECHECK OPEN":s.phase,
     storedProof&&currentIncomplete?"warning":statusClass(s.phase)));

 }else{
   if(s.today && state.latest?.oldCoreRetractedByRuleCorrection===true)
     notice.appendChild(pill("RETRACTED · NEW CORE AWAITED","danger"));
   else notice.appendChild(pill("AWAITING VERIFIED CORE","warning"));
 }
}
function renderPicker(){
 const select=$("slate-select");select.replaceChildren();
 const days=unique([state.latest?.date,...state.archive.map(x=>x.date)]).sort().reverse();
 if(!days.length){
  const o=el("option","","No saved slates");o.value="";select.appendChild(o);
  select.disabled=true;return;
 }
 select.disabled=false;
 for(const date of days){
   const archived=state.archive.find(x=>x.date===date);
   const suffix=archived?.unrestricted?" · unrestricted":archived?" · locked Core":" · awaiting selection";
   const o=el("option","",date+suffix);o.value=date;
   select.appendChild(o);
 }
 select.value=state.selectedDate||days[0];
}
function toggleCardFlip(key){
 if(!key)return;
 state.selectedLeg=key;
 state.flippedLeg=state.flippedLeg===key?null:key;
 document.body?.classList?.toggle("core-report-open",Boolean(state.flippedLeg));
 state.gateFilter="all";
 for(const card of document.querySelectorAll("#core-cards .core-card")){
   const active=card.dataset.leg===state.flippedLeg;
   card.classList.toggle("is-flipped",active);
   card.setAttribute("aria-expanded",String(active));
   card.setAttribute("aria-pressed",String(card.dataset.leg===key));
   const player=card.dataset.player||"player";
   card.setAttribute("aria-label",(active?"Return to front of ":"Flip ")+player+" card");
 }
}
function flipSelectedFromNavigation(){
 const key=state.selectedLeg||(
   selectedEntry()?.current_legs?.[0]?
   String(selectedEntry().current_legs[0].gameId)+":"+
   String(selectedEntry().current_legs[0].playerId):null);
 if(!key)return;
 toggleCardFlip(key);
 const core=$("core");
 if(core)core.scrollIntoView({behavior:"smooth",block:"start"});
}
// NHL pictures are presentation only. Player identities come from saved Core.
function corePhotoTeams(leg){
 const gate=detailsData(leg)?.gateDetails?.find(x=>x.gate==="G0");
 const attacker=gate?.evidence?.selectedAttacker||gate?.evidence?.attacker;
 const match=String(leg.matchup||"").split("@");
 const teams=[leg.team,attacker,...match].filter(x=>typeof x==="string"&&/^[A-Z]{3}$/.test(x));
 return [...new Set(teams)];
}
function corePhoto(leg){
 const art=el("div","card-illustration collector-art");
 const id=String(leg.playerId||"");
 const seasonYear=Number(String(state.selectedDate||"").slice(0,4));
 const season=Number.isInteger(seasonYear)&&seasonYear>=2020&&seasonYear<=2040?
   String(seasonYear)+String(seasonYear+1):"20262027";
 const options=/^\d{7,8}$/.test(id)?[
   ["https://assets.nhle.com/mugs/actionshots/1296x729/"+id+".jpg","action"],
   ...corePhotoTeams(leg).map(team=>[
      "https://assets.nhle.com/mugs/nhl/"+season+"/"+team+"/"+id+".png","headshot"])
 ]:[];
 art.appendChild(el("span","collector-foil-rings"));
 if(options.length){
   let idx=0;
   const img=el("img","collector-photo");
   img.alt=leg.player+" NHL player photo";img.loading="lazy";
   img.decoding="async";img.draggable=false;
   img.addEventListener("load",()=>{
     art.classList.add("has-photo");
     art.classList.toggle("is-headshot",options[idx][1]==="headshot");
   });
   img.addEventListener("error",()=>{
     idx++;
     if(idx<options.length)img.src=options[idx][0];
     else {img.remove();art.classList.add("photo-unavailable");}
   });
   img.src=options[0][0];art.appendChild(img);
 }else art.classList.add("photo-unavailable");
 const shade=el("span","collector-photo-shade");
 shade.setAttribute("aria-hidden","true");art.appendChild(shade);
 const team=leg.team||corePhotoTeams(leg)[0];
 if(team){
   const mark=el("img","collector-team-crest");
   mark.alt="";mark.loading="lazy";
   mark.src="https://assets.nhle.com/logos/nhl/svg/"+team+"_light.svg";
   mark.addEventListener("error",()=>mark.remove());
   art.appendChild(mark);
 }
 const initials=el("span","collector-fallback",String(leg.player||"")
     .split(/\s+/).map(w=>w[0]).join("").slice(0,2).toUpperCase());
 initials.setAttribute("aria-hidden","true");art.appendChild(initials);
 return art;
}
function coreScoringStats(leg){
 if(leg.unrestricted)return "Saved unrestricted selection";
 const ownRelease=detailsData(leg)?.gateDetails?.find(x=>x.gate==="G4")
   ?.evidence?.ownRelease||{};
 const survivor=(state.latest?.gameSurvivorPool||[]).find(x=>
   String(x.gameId)===String(leg.gameId)&&
   String(x.survivor?.playerId)===String(leg.playerId))?.survivor;
 const goals=typeof ownRelease.ownedGoals==="number"?ownRelease.ownedGoals:survivor?.ownedGoals;
 const shots=typeof ownRelease.attempts==="number"?ownRelease.attempts:survivor?.ownShotsOnGoal;
 return typeof goals==="number"&&typeof shots==="number"?
   goals+" credited goals · "+shots+" on-net shots":
   "Original scoring proof on the reverse";
}
function coreCard(leg,i){
 // This real 3-D flip is only an evidence viewer. The saved engine selects.
 const path=auditedPath(leg),key=String(leg.gameId)+":"+String(leg.playerId);
 const button=el("div","core-card "+pathClass(path.display));
 button.setAttribute("role","button");button.tabIndex=0;
 button.dataset.leg=key;button.dataset.player=leg.player;
 button.setAttribute("aria-pressed",String(key===state.selectedLeg));
 button.setAttribute("aria-expanded",String(key===state.flippedLeg));
 button.setAttribute("aria-label",(key===state.flippedLeg?"Return to front of ":"Flip ")+leg.player+" card");
 if(key===state.flippedLeg)button.classList.add("is-flipped");
 const inner=el("div","card-flip-inner");
 const front=el("div","card-face card-front");
 const teams=corePhotoTeams(leg),team=leg.team||teams[0]||"NHL";
 const top=el("div","card-head collector-masthead");
 top.appendChild(el("span","card-index","TRUE BLENDER"));
 top.appendChild(el("span","collector-series","PREMIER · "+String(i+1).padStart(2,"0")+"/03"));
 front.appendChild(top);
 front.appendChild(corePhoto(leg));
 const plate=el("div","card-nameplate collector-nameplate");
 const names=String(leg.player||"").trim().split(/\s+/);
 const surname=names.pop()||"PLAYER";
 plate.appendChild(el("span","collector-given",names.join(" ").toUpperCase()));
 plate.appendChild(el("strong","player-name",surname.toUpperCase()));
 plate.appendChild(el("span","collector-team-line",team+" · "+String(leg.matchup||"").replace("@"," @ ")));
 const route=el("div","collector-path-row");
 route.appendChild(pill(path.display,pathClass(path.display)));
 const origin=String(leg.directRoute||"").split("/").pop().trim();
 route.appendChild(el("span","collector-origin",origin||"SHOT ORIGIN ON BACK"));
 plate.appendChild(route);
 plate.appendChild(el("span","collector-stats",coreScoringStats(leg)));
 if(path.review&&path.display!==path.original)
   plate.appendChild(el("span","collector-original-label","Original: "+path.original));
 front.appendChild(plate);
 const bottom=el("div","card-bottom collector-flip-line");
 bottom.appendChild(el("span","","FLIP FOR SCOUTING EVIDENCE"));
 bottom.appendChild(el("span","tiny-arrow","↗"));
 front.appendChild(bottom);
 inner.appendChild(front);
 const back=el("div","card-face card-back");
 // The collector front stays photo-led. The reverse is the exact same
 // fully source-driven interactive scouting report as the survivor deck.
 const data=detailsData(leg);
 const gateRows=data?.gateDetails;
 const g18=gateRows?.find(x=>x.gate==="G18")?.evidence||{};
 if(leg.unrestricted){const report=el("div","scout-report");const head=el("div","scout-header");head.appendChild(el("strong","",leg.player));const close=el("button","scout-dismiss","CLOSE ✕");close.addEventListener("click",()=>toggleCardFlip(key));head.appendChild(close);report.appendChild(head);const body=el("div","scout-body");body.appendChild(el("h3","","Unrestricted scoring alignment"));body.appendChild(el("p","",leg.directRoute||"Scoring route not included in saved result"));body.appendChild(el("p","","Only evidence supplied by the unrestricted engine is displayed."));report.appendChild(body);back.appendChild(report);}else back.appendChild(NHLScouting.report({
   player:leg.player,team,matchup:leg.matchup,
   stage:data?.stageOfGateRecords||selectedEntry()?.stage,
   path:path.display,goalieId:leg.opposingGoalieId,
   origin:String(leg.directRoute||"").split("/").pop().trim(),
   receipts:gateRows,
   g16Decision:g18.G16FinalistDecision,
   gateNames:EXPLAIN,facts:BlenderGateFacts,
   sources:leg.sourceIds,
   close:()=>toggleCardFlip(key)
 }));
 inner.appendChild(back);
 button.appendChild(inner);
 button.addEventListener("click",event=>{
   // Gate accordions, source links and explicit close buttons remain
   // independent of the physical collector-card flip.
   if(event?.target?.closest?.("a, button, summary, details, .scout-report"))return;
   toggleCardFlip(key);
 });
 button.addEventListener("keydown",event=>{
   if(event.target!==button)return;
   if(event.key==="Enter"||event.key===" "){
     event.preventDefault();toggleCardFlip(key);
   }
 });
 return button;
}
function renderCards(){
 const holder=$("core-cards");holder.replaceChildren();
 const saved=selectedEntry();
 if(!saved?.current_legs?.length){
   holder.appendChild(el("div","empty-state",
     "No source-verified Core is available for this slate. The engine must publish the authoritative card first."));
   return;
 }
 for(const [i,leg] of saved.current_legs.entries())holder.appendChild(coreCard(leg,i));
}
function detailsData(leg){
 if(!state.gateData||state.gateData.cardId!==selectedEntry()?.cardId)return null;
 return state.gateData.legs?.find(x=>String(x.gameId)===String(leg.gameId)
      &&String(x.playerId)===String(leg.playerId))||null;
}
function renderPool(){
 const holder=$("pool-list");if(!holder)return;
 holder.replaceChildren();
 const rows=state.latest?.survivors||[];
 if(!rows.length){holder.appendChild(el("p","empty-state","No unrestricted survivor evidence published."));return;}
 for(const r of rows){const p=el("div","notice");p.appendChild(el("strong","",r.player||r.name||"Unnamed player"));p.appendChild(el("p","",r.matchup||r.team||"Matchup not supplied"));holder.appendChild(p);}
}
function renderAll(){
 renderPicker();renderHeader();renderCards();
 renderPool();
}
async function loadEvidence(date){
 ++state.requestId;state.gateData=null;state.gateLoadError=null;
 renderAll();
}
function chooseDate(date){
 state.selectedDate=date;
 const first=selectedEntry()?.current_legs?.[0];
 state.selectedLeg=first?String(first.gameId)+":"+String(first.playerId):null;
 state.gateFilter="all";state.flippedLeg=null;
 document.body?.classList?.remove("core-report-open");
 renderAll();
 loadEvidence(date);
 const url=new URL(window.location.href);
 url.searchParams.set("slate",date);
 window.history.replaceState(null,"",url);
}
function publishedSignature(latest,archived){
 return JSON.stringify({
   publishedAt:latest?.publishedAt,cardId:latest?.card?.cardId,
   stage:latest?.stage,
   archive:(archived||[]).map(x=>[x.date,x.cardId,x.revision]),
    perGame:(latest?.gameSurvivorPool||[]).map(g=>[g.gameId,g.status,g.survivor?.playerId]),
    savedOriginalGateEvidenceVerified:latest?.savedOriginalGateEvidenceVerified,
 });
}
// Presentation-only section navigation. No changes to picks or evidence.
function initWorkspaceNavigation(){
 const links=Array.from(document.querySelectorAll?.(".main-nav a[data-nav]")||[]);
 if(!links.length)return;
 const ids=["core","pool"];
 const activate=id=>{
   if(!ids.includes(id))return;
   for(const link of links){
     if(link.dataset.nav===id)link.setAttribute("aria-current","page");
     else link.removeAttribute?.("aria-current");
   }
 };
 for(const link of links)
   link.addEventListener("click",()=>activate(link.dataset.nav));
 const fragment=String(window.location?.hash||"").replace("#","");
 activate(ids.includes(fragment)?fragment:"core");
 window.addEventListener?.("hashchange",()=>{
   const id=String(window.location?.hash||"").replace("#","");
   if(ids.includes(id))activate(id);
 });
 // Long card collections can leave the previous tab highlighted with a
 // narrow IntersectionObserver band. Read the actual scroll position.
 const updateFromScroll=()=>{
   if(document.body?.classList?.contains("pool-card-open")||
      document.body?.classList?.contains("core-report-open"))return;
   // The heading is already the active reading section once it enters the
   // upper half of the phone viewport (not only the top third).
   const cutoff=Math.min(540,window.innerHeight*.53);
   let current="core";
   for(const id of ids){
     const rect=$(id)?.getBoundingClientRect?.();
     if(rect&&rect.top<=cutoff)current=id;
   }
   activate(current);
 };
 window.addEventListener?.("scroll",updateFromScroll,{passive:true});
 window.addEventListener?.("resize",updateFromScroll);
 window.addEventListener?.("hashchange",updateFromScroll);
 updateFromScroll();
}
function unrestrictedFeed(u){
 const date=u?.date;
 if(!date||!Array.isArray(u.core)||!String(u.engine||"").startsWith("unrestricted"))return {latest:null,archive:[]};
 const legs=u.core.map(p=>({...p,playerId:p.playerId??p.player_id??p.player,gameId:p.gameId??p.game_id??null,matchup:p.matchup??null,path:"UNRESTRICTED",directRoute:p.directRoute??"Scoring route not included",unrestricted:true}));
 const entry={date,cardId:u.cardId||"unrestricted-"+date,stage:u.stage||"UNRESTRICTED",current_legs:legs,verified:u.verified===true,unrestricted:true,hasGateEvidence:false,grade:u.grade||null,revision:u.revision};
 return {latest:{date,stage:entry.stage,verified:entry.verified,card:{cardId:entry.cardId,current_legs:legs},publishedAt:u.publishedAt,selectionFunnel:{surveyedEligibleSkaters:u.evaluated_players},unrestricted:true,survivors:u.survivors||[]},archive:[entry]};
}
async function boot(){
 $("refresh").addEventListener("click",()=>window.location.reload());
 $("slate-select").addEventListener("change",e=>chooseDate(e.target.value));
 initWorkspaceNavigation();
 for(const id of ["flip-selected-card","flip-from-tray"]){const control=$(id);if(control)control.addEventListener("click",flipSelectedFromNavigation);}
 const u=await json("./data/unrestricted-core.json");
 const feed=unrestrictedFeed(u);
 state.latest=feed.latest;state.archive=feed.archive;
 const days=unique([state.latest?.date,...state.archive.map(x=>x.date)]).sort().reverse();
 const request=new URL(window.location.href).searchParams.get("slate");
 const today=etToday();
 // Show the latest verified original Core, not a blank unissued current slate.
  // The existing header explicitly identifies archived cards.
  const newestVerified=state.archive.map(x=>x.date).sort().reverse()[0];
  const currentIssued=state.latest?.date===today && state.latest?.verified===true &&
    Array.isArray(state.latest?.card?.current_legs) && state.latest.card.current_legs.length>0;
  state.selectedDate=request&&days.includes(request)?request:
    state.archive.some(x=>x.date===today&&x.unrestricted)?today:currentIssued?today:newestVerified||days[0]||null;
 if(!state.selectedDate){
   renderAll();
   $("core-cards").replaceChildren(el("div","empty-state",
      "No verified published slate yet. The automated engine produces the first card."));
   return;
 }
 const first=selectedEntry()?.current_legs?.[0];
 state.selectedLeg=first?String(first.gameId)+":"+String(first.playerId):null;
 renderAll();
 await loadEvidence(state.selectedDate);
 latestPublishedSignature=publishedSignature(state.latest,state.archive);
}
document.addEventListener?.("keydown",event=>{
 if(event.key!=="Escape"||!state.flippedLeg)return;
 toggleCardFlip(state.flippedLeg);
});
boot().catch(e=>{
 setText("hero-phase","DASHBOARD SOURCE ERROR");
 $("core-cards").replaceChildren(el("div","notice warning",
   "The published data could not be read. "+e.message));
});

// An autonomous run can publish while this tab is open. Refresh ONLY after
// the authoritative feed changes; preserve the user's selected slate/card
// and never re-run scorer selection from client-side code.
let latestPublishedSignature=null;
async function pollPublishedResults(){
 if(document.hidden)return;
 const feed=unrestrictedFeed(await json("./data/unrestricted-core.json"));
 const next=feed.latest, archived=feed.archive;
 if(!next)return;
 const fingerprint=publishedSignature(next,archived);
 if(fingerprint===latestPublishedSignature)return;
 latestPublishedSignature=fingerprint;
 const previous=state.latest;
 state.latest=next;state.archive=archived;
 // Automatically show the newly issued current Core when it first arrives.
 // Do not replace a deliberate archived selection after today was already issued.
 const days=unique([next.date,...archived.map(x=>x.date)]);
 const newlyIssuedToday=next.date===etToday() && next.verified===true &&
   Array.isArray(next.card?.current_legs) && next.card.current_legs.length>0 &&
   !(previous?.verified===true && previous?.date===next.date &&
     Array.isArray(previous?.card?.current_legs) && previous.card.current_legs.length>0);
 if(newlyIssuedToday || !days.includes(state.selectedDate)){
   state.selectedDate=newlyIssuedToday?next.date:days[0]||null;
   const first=selectedEntry()?.current_legs?.[0];
   state.selectedLeg=first?String(first.gameId)+":"+String(first.playerId):null;
   state.flippedLeg=null;state.gateFilter="all";
   document.body?.classList?.toggle("core-report-open",false);
 }
 renderAll();
 if(state.selectedDate)await loadEvidence(state.selectedDate);
}
setInterval(()=>{pollPublishedResults().catch(()=>{});},120000);
document.addEventListener("visibilitychange",()=>{
 if(!document.hidden)pollPublishedResults().catch(()=>{});
});
