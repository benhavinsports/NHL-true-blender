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
 latest:null,archive:[],season:null,selectedDate:null,selectedLeg:null,
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
 // Display only grounded saved-source numbers, never inferred picks.
 const publicGames=isLatest()?(state.latest?.gameSurvivorPool||[]):[];
 const qualified=publicGames.filter(g=>g.status==="SURVIVOR"&&g.survivor).length;
 const sourceStage=isLatest()&&publicGames.length?(
   state.latest?.gameSurvivorDisplayProvenance?.sourceStage||
   state.latest?.gameSurvivorDisplayStage||state.latest?.stage):null;
 setText("overview-core-count",count?String(count):"—");
 setText("overview-survivor-count",publicGames.length?
   String(qualified)+" / "+String(publicGames.length):"—");
 setText("overview-source-phase",sourceStage||"—");
 setText("stat-legs",count?count+" / "+(count===2?"2":"3"):"—");
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
 if(!s.today&&saved){
   notice.appendChild(pill("ARCHIVED · "+date,"warning"));
   notice.appendChild(el("p","","This is a previously locked slate, not a new pick for today. Select a different date to inspect another card."));
 }else if(saved){
   const storedProof=s.current&&state.latest?.savedOriginalGateEvidenceVerified===true;
   const currentIncomplete=s.current&&state.latest?.currentRunFullyCertified!==true;
   notice.appendChild(pill(storedProof&&currentIncomplete?
     "SAVED ORIGINAL CORE · CURRENT RECHECK OPEN":s.phase,
     storedProof&&currentIncomplete?"warning":statusClass(s.phase)));
   if(storedProof&&currentIncomplete)
     notice.appendChild(el("span","phase-quiet","Saved Core · source recheck open"));
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
   const suffix=archived?" · locked Core":" · awaiting selection";
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
 const teams=[attacker,...match].filter(x=>typeof x==="string"&&/^[A-Z]{3}$/.test(x));
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
 const team=corePhotoTeams(leg)[0];
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
 const teams=corePhotoTeams(leg),team=teams[0]||"NHL";
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
 back.appendChild(NHLScouting.report({
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
 const pool=isLatest()?(state.latest?.gameSurvivorPool||[]):[];
 const byId=new Map(pool.map(g=>[String(g.gameId),g]));
 const allGames=state.gateData?.games||[];
 const games=allGames.length?allGames.map(g=>byId.get(String(g.gameId))||{
    gameId:g.gameId,matchup:g.away+"@"+g.home,gameStartUTC:g.startUTC,
    status:"SOURCE_RECEIPT_MISSING"}):pool;
 ElitePool.render({
   holder,games,coreLegs:selectedEntry()?.current_legs||[],
   latest:isLatest()?state.latest:null,
   gates:MASTER,gateNames:EXPLAIN,facts:BlenderGateFacts,
   date:state.selectedDate
 });
}
function renderMatchups(){
 const holder=$("matchup-list");holder.replaceChildren();
 const games=state.gateData?.games||[];
 if(!games.length){
   holder.appendChild(el("div","empty-state","The game-by-game source summary is available after the next independent engine export."));
   return;
 }
 for(const game of games){
   const panel=el("article","match");
   const head=el("div","match-head");
   head.appendChild(el("strong","",game.away+" @ "+game.home));
   head.appendChild(pill(game.gameState||"SCHEDULED",statusClass(game.gameState)));
   panel.appendChild(head);
   panel.appendChild(el("p","","Puck drop · "+etTime(game.startUTC)));
   const disclosure=el("details");
   disclosure.appendChild(el("summary","","Goalies, rosters & defense sources"));
   const group=el("div","match-data");
   for(const team of [game.away,game.home]){
     const part=el("div","match-team");
     part.appendChild(el("strong","",team+" · goalie and roster evidence"));
     const goalies=game.goaliesByTeam?.[team]||[];
     for(const g of goalies){
       const line=el("div","","Goalie ID "+(g.goalieId||"?")+" · "+(g.status||"unverified")+
          " · "+Object.keys(g.weakZones||{}).length+" measured vulnerable origin"+(Object.keys(g.weakZones||{}).length===1?"":"s"));
       part.appendChild(line);
       const a=link(g.sourceUrl,"Starter report");
       if(a){part.appendChild(a);part.appendChild(el("span",""," · "));}
       const b=link(g.profileSourceUrl,"Goalie profile");
       if(b)part.appendChild(b);
     }
     if(!goalies.length)part.appendChild(el("div","","No evidenced goalie branch in this export."));
     const roster=game.rostersByTeam?.[team]||{};
     part.appendChild(el("div","","Current roster: "+number(roster.rosterPlayers)+
       " skaters · "+Object.entries(roster.availabilityReports||{}).map(([k,v])=>k+" "+v).join(" / ")));
     const rosterLink=link(roster.sourceUrl,"Roster source");if(rosterLink)part.appendChild(rosterLink);
     part.appendChild(el("div","","Recent-form logs with dated pressure data: "+
       number(roster.recentFormEvidenceCount)+" roster players"));
     if(roster.unavailablePlayers?.length){
       part.appendChild(el("div","","Reported availability: "+
         roster.unavailablePlayers.map(p=>p.name+" ("+p.status+")").join(", ")));
     }
     if(roster.deploymentEvidence?.length){
       const lines=el("details","source-details");
       lines.appendChild(el("summary","","View "+roster.deploymentEvidence.length+
         " separately sourced EV / PP / PK assignments"));
       const list=el("div","match-data");
       for(const d of roster.deploymentEvidence){
         const row=el("div","match-team");
         row.appendChild(el("strong","",d.name||"Player "+d.playerId));
         row.appendChild(el("div","",[
           "EV "+(d.EV||"not reported"),
           "PP "+(d.PP||"not reported"),
           "PK "+(d.PK||"not reported"),
           d.status||"status not reported"
         ].join(" · ")));
         const src=link(d.sourceUrl,"Lineup and PP unit source");
         if(src)row.appendChild(src);
         list.appendChild(row);
       }
       lines.appendChild(list);part.appendChild(lines);
     }else part.appendChild(el("div","","No independently sourced line or PP assignments in this export."));
     const c=game.defenseByAttackingTeam?.[team]||{};
     part.appendChild(el("div","","Opponent coverage green zones: "+
         (c.greenWeakZones?.join(", ")||"not reported")));
     part.appendChild(el("div","","Opponent coverage avoid zones: "+
         (c.redStrongZones?.join(", ")||"not reported")));
     const covLink=link(c.sourceUrl,"Defensive coverage evidence");
     if(covLink){part.appendChild(covLink);}
     group.appendChild(part);
   }
   disclosure.appendChild(group);panel.appendChild(disclosure);
   holder.appendChild(panel);
 }
}
function renderGrade(){
 const saved=selectedEntry(),holder=$("grade-summary");holder.replaceChildren();
 const grade=saved?.grade||(isLatest()?state.latest?.postgameGrade:null);
 if(!saved){
   holder.appendChild(el("div","notice","Official grade is available only for a saved original Core card."));
   return;
 }
 if(!grade||grade.cardId!==saved.cardId){
   holder.appendChild(el("div","notice","Original Core locked. The independent grade begins after every game is officially final; no result is invented."));
   return;
 }
 const result=grade.result;
 if(!["WIN","LOSS"].includes(result)||typeof grade.hits!=="number"||
    grade.legs!==saved.current_legs.length){
   holder.appendChild(el("div","notice warning","The grade does not reconcile to the original card; no outcome is displayed."));
   return;
 }
 const box=el("div","stat-card");
 box.appendChild(pill(result,statusClass(result)));
 box.appendChild(el("strong","",grade.hits+" / "+grade.legs));
 box.appendChild(el("p","","Official credited goal scorers · original card ID preserved"));
 holder.appendChild(box);
 const lines=el("div","grade-lines");
 for(const p of grade.playerResults||[]){
   const d=el("div","grade-line");
   d.appendChild(el("span","",p.player+" · "+p.goals+" goal"+(p.goals===1?"":"s")));
   d.appendChild(pill(p.result,statusClass(p.result)));lines.appendChild(d);
 }
 holder.appendChild(lines);
 // Original saved recipient-vs-actual scorer audit, re-checked against
 // every official NHL goal in these three matchups. This is not a re-pick.
 const recipientReview=grade.postgameRecipientAudit||{};
 if(recipientReview.status==="OFFICIALLY_VERIFIED_FULL_SCORER_COMPARISON" &&
    recipientReview.cardId===saved.cardId){
   const auditBox=el("details","collapse");
   const summary=el("summary","","Flip postgame scorer audit • who scored instead?");
   auditBox.appendChild(summary);
   const important=el("div","notice warning",
     "Retrospective outcome comparison, NOT a new Core or proof that an alternative scorer could have been known with certainty before puck drop.");
   auditBox.appendChild(important);
   for(const game of recipientReview.selectedLegs||[]){
     const g=el("article","match");
     const top=el("div","match-head");
     top.appendChild(el("strong","",game.lockedPlayer));
     top.appendChild(pill(game.chosenGoals?"HIT":"MISS",
                             game.chosenGoals?"success":"danger"));
     g.appendChild(top);
     g.appendChild(el("p","",game.matchup+" • "+game.lockedTeam+
       " goals: "+game.sameAttackSideGoals+
       " • Opposing goals: "+game.oppositeAttackSideGoals));
     const scorers=el("div","grade-lines");
     for(const rival of game.officialScorers||[]){
       const row=el("div","grade-line");
       const fact=el("div");
       fact.appendChild(el("strong","",rival.player+" · "+rival.goals+
         " goal"+(rival.goals===1?"":"s")));
       fact.appendChild(el("p","tiny muted",
         rival.team+" · "+(rival.pregameG105Verdict?
            "Original G10.5: "+rival.pregameG105Verdict:
            rival.reasonNotPregameG105Compared==="OPPOSITE_G0_ATTACK_SIDE"?
             "Outside selected G0 attack direction":"Original saved scorer")));
       row.appendChild(fact);
       if(rival.pregameG105Verdict==="DEFEATED")row.appendChild(pill("G10.5 REVIEW","warning"));
       scorers.appendChild(row);
     }
     g.appendChild(scorers);
     if((game.auditFlags||[]).includes("ORIGINAL_G15_WAS_NOT_INDEPENDENT_FINISHER_PROOF")){
       g.appendChild(el("p","archive-note",
         "Audit: The old G15 PASS repeated historical goal credit rather than independently proving the future finishing role. Future G15 has been corrected."));
     }
     if(game.bothGoalieDirectionsWereFullySourceReviewedBeforePuck===false){
       g.appendChild(el("p","archive-note",
         "Pregame G0 source gap: Both opposing goalie attack directions were NOT independently evidenced before puck drop. The saved result cannot establish that the Blender compared both goalies completely."));
     }
     const sources=el("div","source-links");
     unique(game.officialSources||[]).map(u=>link(u,"Official NHL scoring record")).filter(Boolean)
          .forEach(a=>sources.appendChild(a));
     g.appendChild(sources);
     auditBox.appendChild(g);
   }
   holder.appendChild(auditBox);
 }else if(recipientReview.status){
   holder.appendChild(el("div","notice",
     "Detailed scorer-versus-recipient audit: "+recipientReview.status.replace(/_/g," ")+
     ". The frozen official card grade remains unchanged."));
 }
 const audits=grade.missAudits||[];
 const p=el("p","small muted","Miss audits saved: "+audits.length+
    " · Verified future-only policy guards: "+(grade.patchesApplied?.length||0)+
    ". An ordinary miss does not change the rules.");
 holder.appendChild(p);
 const sourceList=el("details","collapse");
 sourceList.appendChild(el("summary","","Official scoring receipts"));
 const sourceBox=el("div","source-links");
 unique(grade.officialSources||[]).map(u=>link(u)).filter(Boolean).forEach(a=>sourceBox.appendChild(a));
 sourceList.appendChild(sourceBox);holder.appendChild(sourceList);
}
function renderSeason(){
 const host=$("season-summary");host.replaceChildren();
 const history=state.season||{};
 if(!history.officiallyGradedSlates){
   host.appendChild(el("div","notice","No verified season performance totals have been published yet. Grades and recalibration appear here after official final games."));
   return;
 }
 const grid=el("div","system-grid");
 for(const [label,num] of [["Wins",history.wins],["Losses",history.losses],["Individual goals",history.legHits+" / "+history.legOpportunities]]){
   const d=el("div","system-stat");
   d.appendChild(el("strong","",num));d.appendChild(el("span","",label));grid.appendChild(d);
 }
 host.appendChild(grid);
 const month=el("details","collapse");
 month.appendChild(el("summary","","Monthly recalibration • real graded slates only"));
 for(const [period,summary] of Object.entries(history.monthlyThreeSlateCalibration||{})){
   month.appendChild(el("p","",period+" · "+summary.gradedSlatesAvailable+
    " officially graded · "+summary.sampleCount+" recalibration samples · "+
    summary.wins+" WIN / "+summary.losses+" LOSS"));
 }
 host.appendChild(month);
 const patches=history.verifiedAutomaticGuardPatches||[];
 host.appendChild(el("div","notice",patches.length?
   "Source-validated future-only gate guards: "+patches.join(", "):
   "No verified gate-contradiction patches have been activated. Misses alone cannot activate a correction."));
 const raw=el("a","small","Read official season history");
 raw.href="./data/season-history.json";raw.rel="noopener noreferrer";raw.target="_blank";
 host.appendChild(raw);
}
function renderSystem(){
 const host=$("system-summary");host.replaceChildren();
 const x=isLatest()?state.latest||{}:{};
 const audit=x.gateCertification||{};
 const saved=selectedEntry();
 const grid=el("div","system-grid");
 const rows=[
  ["Games surveyed",number(x.games||state.gateData?.games?.length)],
  ["Skaters evaluated",number(x.selectionFunnel?.surveyedEligibleSkaters||x.eligibleSkaterRows)],
  ["Source gate rows",number(x.gateRows)],
  ["Locked core legs",number(saved?.current_legs?.length)],
  ["Selected gate pass",audit.selectedCoreOnlyFullyCertified===true?"YES":
      saved?.verified===true?"SAVED":"—"],
  ["Original revision",number(saved?.revision)]
 ];
 for(const [label,value] of rows){const d=el("div","system-stat");d.appendChild(el("strong","",value));d.appendChild(el("span","",label));grid.appendChild(d);}
 host.appendChild(grid);
 const twoGoalieDecisions=x.g0TwoGoalieDirectionDecisions||{};
 if(Object.keys(twoGoalieDecisions).length){
   const panel=el("details","collapse");
   const ready=Object.keys(twoGoalieDecisions).length;
   panel.appendChild(el("summary","",
     "G0 · BOTH goalies reviewed • "+ready+" game"+(ready===1?"":"s")+" source-selected"));
   panel.appendChild(el("p","small muted",
     "Source-backed goalie direction is decided before any skater gates. NHL EDGE origin percentile is not glove, blocker, or five-hole location."));
   for(const [gameId,entry] of Object.entries(twoGoalieDecisions)){
     const game=el("div","match");
     const head=el("div","match-head");
     head.appendChild(el("strong","",entry.attackingTeam+" ATTACKS "+entry.targetGoalieTeam+" • GAME "+gameId));
     head.appendChild(pill(entry.bothGoaliesReviewedFirst===true?"2 GOALIES VERIFIED":"G0 SOURCE GAP",
         entry.bothGoaliesReviewedFirst===true?"success":"warning"));
     game.appendChild(head);
     const proof=entry.decisionEvidence||{};
     game.appendChild(el("p","small muted","Evidence method: "+
        (entry.goalieSourceMethod||"Source-scoped goalie comparison").replace(/_/g," ")));
     if(proof.winnerWeakOrigin){
       game.appendChild(el("p","",
          "Attacked goalie: "+proof.winnerWeakOrigin+" · save% peer percentile: "+
          proof.winnerGoaliePeerSavePercentile+" · "+proof.winnerGoalsAllowedFromOrigin+
          " allowed / "+proof.winnerGoalieOnNetShots+" on-net shots"));
       game.appendChild(el("p","",
          "Opposite goalie: "+proof.oppositeWeakOrigin+" · save% peer percentile: "+
          proof.oppositeGoaliePeerSavePercentile+" · "+proof.oppositeGoalsAllowedFromOrigin+
          " allowed / "+proof.oppositeGoalieOnNetShots+" on-net shots"));
     }
     const urls=el("div","source-links");
     unique(proof.goalieSourceUrls||[]).map(u=>link(u,"NHL goalie evidence"))
        .filter(Boolean).forEach(a=>urls.appendChild(a));
     game.appendChild(urls);panel.appendChild(game);
   }
   const fallback=x.g0OfficialPbpFallback||{};
   if(fallback.status){
      panel.appendChild(el("p","small muted",
       "Historical PBP fallback: "+fallback.status.replace(/_/g," ")+
       " · goalie profiles recovered: "+(fallback.fallbackProfiles||0)));
   }
   host.appendChild(panel);
 }
 if(x.lineupSourceCoverage||x.edgeSourceCoverage){
   const sources=el("details","collapse");
   sources.appendChild(el("summary","","Official source connection summary"));
   for(const [label,val] of [["Goalie/skater EDGE",x.edgeSourceCoverage],
                            ["Lineups and PP",x.lineupSourceCoverage],
                            ["Historical defensive shifts",x.historicalShiftCoverage]]){
       if(!val||!Object.keys(val).length)continue;
       const inner=el("details","code-details");
       inner.appendChild(el("summary","",label));
       inner.appendChild(el("pre","raw-json",JSON.stringify(val,null,2)));
       sources.appendChild(inner);
   }
   host.appendChild(sources);
 }
 const details=el("details","collapse");
 details.appendChild(el("summary","","Full-pool elimination audit (not Core certification errors)"));
 const funnel=x.selectionFunnel||{};
 details.appendChild(el("p","","Evaluated "+number(funnel.surveyedEligibleSkaters)+
   " skaters. Gate-eliminated: "+number(funnel.sourceEliminated)+
   ". Insufficient evidence: "+number(funnel.notQualifiedIncompleteEvidence)+
   ". Qualified but not selected: "+number(funnel.qualifiedButNotChosen)+
   ". Rejected-player failures do not invalidate the certified Core."));
 const g16=x.g16FinalistCompetition;
 if(g16&&Array.isArray(g16.finalists)){
   details.appendChild(el("p","","G16 cross-game finalist competition ("+
     g16.finalistCount+" per-game survivors for Core "+g16.requiredCoreSize+"): "+
     g16.finalists.map(f=>f.player+" "+f.ownedGoalsInMatchedLane+"G/"+
       f.ownShotsOnGoalInMatchedLane+"SOG "+f.routeZone+" — "+
       (String(f.g16Decision||"").startsWith("RETAINED")?"retained":
        "excluded (dominated by "+(f.dominatedBy||[]).length+")")).join(" • ")));
 }
 if(x.errors?.length)details.appendChild(el("p","",
   "Actual execution errors: "+x.errors.join(" • ")));
 if(x.nonselectedGameResearchNotes?.length)details.appendChild(el("p","",
    "Unselected matchup research: "+x.nonselectedGameResearchNotes.join(" • ")));
 host.appendChild(details);
}
function renderCompleteGateDeck(){
  // One gate deck; original source functions are nested under each gate.
  // This deck is navigation only and never changes a Blender decision.
  for(const [id,gates,type] of [
    ["master-gate-deck",MASTER,"all"]
  ]){
    const holder=$(id);
    if(!holder)continue;
    holder.replaceChildren();
    for(const [i,gate] of gates.entries()){
      const card=el("button","gate-mini-card gate-mini-"+(i%5));
      card.type="button";
      card.dataset.gate=gate;
      card.setAttribute("aria-label","Inspect "+gate+": "+(EXPLAIN[gate]||"Gate evidence"));
      card.appendChild(el("span","mini-gate-code",gate));
      card.appendChild(el("span","mini-gate-symbol","♠"));
      card.appendChild(el("span","mini-gate-title",EXPLAIN[gate]||"Source check"));
      card.addEventListener("click",()=>{
        const saved=selectedEntry(),leg=saved?.current_legs?.find(x=>
          String(x.gameId)+":"+String(x.playerId)===state.selectedLeg)||
          saved?.current_legs?.[0];
        if(!leg)return;
        const key=String(leg.gameId)+":"+String(leg.playerId);
        if(state.flippedLeg!==key)toggleCardFlip(key);
        const coreCard=[...document.querySelectorAll("#core-cards .core-card")]
          .find(x=>x.dataset.leg===key);
        if(!coreCard)return;
        coreCard.scrollIntoView({behavior:"smooth",block:"center"});
        const back=coreCard.querySelector(".card-back");
        const target=[...coreCard.querySelectorAll(".flip-gate-row")]
          .find(x=>x.dataset.gate===gate);
        if(back&&target)back.scrollTop=target.offsetTop-back.offsetTop;
      });
      holder.appendChild(card);
    }
  }
}
function renderAll(){
 renderPicker();renderHeader();renderCards();
 renderPool();renderGrade();renderSeason();
}
async function loadEvidence(date){
 const seq=++state.requestId;state.gateLoadError=null;state.gateData=null;
 const entry=state.archive.find(x=>x.date===date);
 if(entry?.hasGateEvidence===false){
    state.gateLoadError=entry.gateEvidenceError||
      "This archived card has no verified selected-player gate export yet.";
    renderAll();return;
 }
 try{
   const data=await json("./data/slates/"+encodeURIComponent(date)+".json");
   if(seq!==state.requestId)return;
   const saved=selectedEntry();
   if(!data||!data.readOnly||!data.doesNotSelectOrReplaceScorers||
      (saved&&data.cardId!==saved.cardId)||
      (saved&&data.fingerprint!==saved.fingerprint)){
     throw Error("Gate evidence does not match the single authoritative card.");
   }
   state.gateData=data;
 }catch(e){
   if(seq!==state.requestId)return;
   state.gateLoadError=e.message;
 }
 if(seq===state.requestId)renderAll();
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
function publishedSignature(latest,archived,season){
 return JSON.stringify({
   publishedAt:latest?.publishedAt,cardId:latest?.card?.cardId,
   stage:latest?.stage,grade:latest?.postgameGrade?.result,
   archive:(archived||[]).map(x=>[x.date,x.cardId,x.revision,x.grade?.result]),
    perGame:(latest?.gameSurvivorPool||[]).map(g=>[g.gameId,g.status,g.survivor?.playerId]),
    savedOriginalGateEvidenceVerified:latest?.savedOriginalGateEvidenceVerified,
   seasonSize:season?.officiallyGradedSlates,
   patchCount:season?.verifiedAutomaticGuardPatches?.length,
 });
}
// Presentation-only section navigation. No changes to picks or evidence.
function initWorkspaceNavigation(){
 const links=Array.from(document.querySelectorAll?.(".main-nav a[data-nav]")||[]);
 if(!links.length)return;
 const ids=["core","pool","results"];
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
 if(typeof IntersectionObserver!=="undefined"){
   const observer=new IntersectionObserver(entries=>{
     const active=entries.filter(item=>item.isIntersecting);
     if(!active.length||document.body?.classList?.contains("pool-card-open")||
          document.body?.classList?.contains("core-report-open"))return;
     active.sort((a,b)=>b.intersectionRatio-a.intersectionRatio);
     activate(active[0].target.id);
   },{rootMargin:"-24% 0px -57% 0px",threshold:[0,.15,.4]});
   for(const id of ids){
     const target=$(id);
     if(target)observer.observe(target);
   }
 }
}
async function boot(){
 $("refresh").addEventListener("click",()=>window.location.reload());
 $("slate-select").addEventListener("change",e=>chooseDate(e.target.value));
 initWorkspaceNavigation();
 for(const id of ["flip-selected-card","flip-from-tray"]){const control=$(id);if(control)control.addEventListener("click",flipSelectedFromNavigation);}
 const values=await Promise.allSettled([
   json("./data/latest.json"),json("./data/cards-archive.json"),
   json("./data/season-history.json")
 ]);
 state.latest=values[0].status==="fulfilled"?values[0].value:null;
 state.archive=values[1].status==="fulfilled"?
    (values[1].value.cards||[]).filter(x=>x.verified===true&&Array.isArray(x.current_legs)):[];
 state.season=values[2].status==="fulfilled"?values[2].value:null;
 const days=unique([state.latest?.date,...state.archive.map(x=>x.date)]).sort().reverse();
 const request=new URL(window.location.href).searchParams.get("slate");
 const today=etToday();
 state.selectedDate=request&&days.includes(request)?request:
    days.includes(today)?today:days[0]||null;
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
 latestPublishedSignature=publishedSignature(state.latest,state.archive,state.season);
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
 if(document.hidden||!state.selectedDate)return;
 const fresh=await Promise.allSettled([
   json("./data/latest.json"),
   json("./data/cards-archive.json"),
   json("./data/season-history.json")
 ]);
 if(fresh[0].status!=="fulfilled"||fresh[1].status!=="fulfilled")return;
 const next=fresh[0].value;
 const archived=(fresh[1].value.cards||[]).filter(x=>
   x.verified===true&&Array.isArray(x.current_legs));
 const season=fresh[2].status==="fulfilled"?fresh[2].value:state.season;
 const fingerprint=publishedSignature(next,archived,season);
 if(latestPublishedSignature===null){
   latestPublishedSignature=fingerprint;
   return;
 }
 if(fingerprint===latestPublishedSignature)return;
 latestPublishedSignature=fingerprint;
 state.latest=next;state.archive=archived;state.season=season;
 // Keep the user's open archive date and selected recipient when possible.
 const days=unique([next.date,...archived.map(x=>x.date)]);
 if(!days.includes(state.selectedDate))
   state.selectedDate=days[0]||null;
 renderAll();
 if(state.selectedDate)await loadEvidence(state.selectedDate);
}
setInterval(()=>{pollPublishedResults().catch(()=>{});},120000);
document.addEventListener("visibilitychange",()=>{
 if(!document.hidden)pollPublishedResults().catch(()=>{});
});
