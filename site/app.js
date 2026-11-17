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
 gateFilter:"all",gateData:null,gateLoadError:null,requestId:0,
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
 setText("stat-legs",count?count+" / "+(count===2?"2":"3"):"—");
 setText("stat-phase",saved?s.phase:"AWAITING");
 const valid=state.gateData?.legs?.every(x=>x.masterPassed===x.totalMaster
     &&x.overlayPassed===x.totalOverlay);
 setText("stat-gates",valid?"36 / 36":saved&&state.gateData?"REVIEW":"—");
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
   notice.appendChild(pill(s.phase,statusClass(s.phase)));
   notice.appendChild(el("p","",s.certified?
     "One saved Core. Selection and gate records are preserved in the official engine ledger.":
     "Original Core retained. Check the selected-leg evidence before treating the latest run as fully certified."));
 }else{
   notice.appendChild(pill("WAITING FOR VERIFIED CORE","warning"));
   notice.appendChild(el("p","","The dashboard never generates a fallback pick. The next Core appears only after the autonomous Blender publishes its verified card."));
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
function coreCard(leg,i){
 // Player names, paths, game, puck drop, source route and card identity
 // all come from the ONE saved Blender Core. This styling never picks.
 const path=auditedPath(leg);
 const button=el("button","core-card "+pathClass(path.display));
 button.type="button";
 const key=String(leg.gameId)+":"+String(leg.playerId);
 button.setAttribute("aria-pressed",String(key===state.selectedLeg));
 button.setAttribute("aria-label","Flip "+leg.player+
   " card to inspect 20 G gates, 16 overlay checks and their sources");
 // A playing-card suit is decorative, never a scorer rank or calculated chance.
 const suit=path.display==="TRANSFER"?"♦":path.display==="WHO"?"♣":"♠";
 const top=el("div","card-head");
 top.appendChild(el("span","card-index","CORE "+String(i+1).padStart(2,"0")));
 top.appendChild(pill(path.display,pathClass(path.display)));
 button.appendChild(top);
 const artwork=el("div","card-illustration");
 artwork.appendChild(el("span","face-corner top",suit));
 const rink=el("div","rink-center");
 rink.appendChild(el("span","card-emblem","◉"));
 artwork.appendChild(rink);
 artwork.appendChild(el("span","face-corner bottom",suit));
 button.appendChild(artwork);
 const plate=el("div","card-nameplate");
 plate.appendChild(el("div","player-name",leg.player));
 plate.appendChild(el("div","card-match",
   String(leg.matchup||"Game source unavailable").replace("@"," @ ")));
 button.appendChild(plate);
 const metadata=el("div","card-meta");
 metadata.appendChild(el("div","","PUCK DROP · "+etTime(leg.startUTC)));
 metadata.appendChild(el("div","","GOAL ROUTE · "+(leg.directRoute||"Open source details")));
 if(path.review&&path.display!==path.original)
   metadata.appendChild(el("div","tiny","Original frozen label: "+path.original));
 button.appendChild(metadata);
 const bottom=el("div","card-bottom");
 bottom.appendChild(el("span","","FLIP • INSPECT 36 GATES"));
 bottom.appendChild(el("span","tiny-arrow","↻"));
 button.appendChild(bottom);
 button.addEventListener("click",()=>{
   state.selectedLeg=key;state.gateFilter="all";
   renderCards();renderDetails();
   const detail=$("evidence");
   if(detail)detail.scrollIntoView({behavior:"smooth",block:"start"});
 });
 return button;
}

function renderCards(){
 const holder=$("core-cards");holder.replaceChildren();
 const saved=selectedEntry();
 if(!saved?.current_legs?.length){
   holder.appendChild(el("div","empty-state","No source-verified Core is available for this slate. The engine must publish the authoritative card first."));
   $("leg-detail").hidden=true;
   return;
 }
 $("leg-detail").hidden=false;
 for(const [i,leg] of saved.current_legs.entries())holder.appendChild(coreCard(leg,i));
}
function detailsData(leg){
 if(!state.gateData||state.gateData.cardId!==selectedEntry()?.cardId)return null;
 return state.gateData.legs?.find(x=>String(x.gameId)===String(leg.gameId)
      &&String(x.playerId)===String(leg.playerId))||null;
}
function getMatch(leg){
 return state.gateData?.games?.find(x=>String(x.gameId)===String(leg.gameId));
}
function scorerOpponent(leg,game){
 if(!game)return null;
 const gameAway=String(game.away),gameHome=String(game.home);
 const matchup=String(leg.matchup||"").replace(/ /g,"");
 const attacker=matchup.split("@")[0];
 const defendant=attacker===gameAway?gameHome:attacker===gameHome?gameAway:null;
 return defendant;
}
function fact(label,value){
 const d=el("div","fact");
 d.appendChild(el("span","",label));
 d.appendChild(el("b","",value===null||value===undefined||value===""?"Not reported":value));
 return d;
}
function renderDetails(){
 const saved=selectedEntry(),section=$("leg-detail");
 section.replaceChildren();
 if(!saved?.current_legs?.length){section.hidden=true;return;}
 section.hidden=false;
 let leg=saved.current_legs.find(x=>
   String(x.gameId)+":"+String(x.playerId)===state.selectedLeg);
 if(!leg){leg=saved.current_legs[0];state.selectedLeg=String(leg.gameId)+":"+String(leg.playerId);}
 const path=auditedPath(leg),data=detailsData(leg),match=getMatch(leg);
 const header=el("div","detail-head");
 const intro=el("div");
 intro.appendChild(el("span","eyebrow","SELECTED CORE · SOURCE AUDIT"));
 intro.appendChild(el("h3","",leg.player));
 intro.appendChild(el("p","","Every gate is a real pre-puck receipt when available. The engine—not this webpage—determines the scorer and path."));
 header.appendChild(intro);
 const tag=el("div");tag.appendChild(pill(path.display,pathClass(path.display)));
 if(path.original!==path.display)tag.appendChild(el("p","tiny","Original: "+path.original));
 header.appendChild(tag);section.appendChild(header);
 const opponent=scorerOpponent(leg,match);
 const goalie=match?.goaliesByTeam?.[opponent]?.find(x=>String(x.goalieId)===String(leg.opposingGoalieId));
 const facts=el("div","fact-row");
 facts.appendChild(fact("Matchup",leg.matchup||match?.matchup));
 facts.appendChild(fact("Puck drop (ET)",etTime(leg.startUTC)));
 facts.appendChild(fact("Opposing goalie",leg.opposingGoalieId?
   "NHL ID "+leg.opposingGoalieId+(goalie?.status?" · "+goalie.status:""):
   "Not sourced"));
 facts.appendChild(fact("Credited scoring origin",leg.directRoute||"Not sourced"));
 section.appendChild(facts);
 const body=el("div","gate-area");
 const compliance=el("div","phase-bar");
 const summary=el("div");
 summary.appendChild(el("strong","","Full gate evidence"));
 const passed=data?data.masterPassed+" / "+data.totalMaster+" master · "+
   data.overlayPassed+" / "+data.totalOverlay+" overlay":"No separately exported pre-puck matrix yet";
 summary.appendChild(el("p","",passed+
   (data?" · "+(data.executionOrderVerified?"exact execution order verified":"execution order NOT verified")+
     " · Source stage: "+(data.stageOfGateRecords||"Unavailable"):"")));
 compliance.appendChild(summary);
 const passedAll=data&&data.executionOrderVerified===true&&
   data.masterPassed===data.totalMaster&&data.overlayPassed===data.totalOverlay;
 compliance.appendChild(pill(data?passedAll?"ALL 36 PASSED · ORDER VERIFIED":"EVIDENCE REVIEW":"AWAITING EXPORT",
     data?passedAll?"success":"warning":"neutral"));
 body.appendChild(compliance);
 if(state.gateData?.currentEngineUsesDifferentOverlayPlacement){
   body.appendChild(el("div","notice warning",
      "This original projected receipt is preserved in its actual historic execution order: G0–G17, overlay 0–14, then G18. It contains 36 recorded PASS checks, but does NOT claim the newer interleaved overlay order was executed on that historical run."));
 }
 // These are independent source reviews, not two different Core cards.
 // A later incomplete confirmation must never hide the original verified
 // projected receipt or visually promote a projected lineup to confirmed.
 if(data?.separatePhaseReviews){
   const reviews=el("div","fact-row");
   for(const phase of ["PROJECTED","CONFIRMED"]){
     const r=data.separatePhaseReviews[phase];
     if(!r)continue;
     const label=phase+(data.stageOfGateRecords===phase?" · SHOWN ABOVE":" · REVIEW ONLY");
     const status=!r.available?"NOT COLLECTED":
       r.fullOriginalOrderPass?"36/36 SOURCE PASSES":
       r.masterPassed+" / 20 master · "+r.overlayPassed+" / 16 overlay";
     reviews.appendChild(fact(label,status));
   }
   body.appendChild(reviews);
   if(data.latestReviewStage==="CONFIRMED" &&
      data.stageOfGateRecords==="PROJECTED"){
     body.appendChild(el("div","notice warning",
       "Confirmed-source review has unresolved gates. The card and gate details above retain the earlier verified projected evidence; no new Core was issued."));
   }
 }
 if(!data){
   body.appendChild(el("div","notice warning",state.gateLoadError||
     "Selected-player source receipts are not available in the deployed evidence export. A PASS is not assumed."));
 }else{
   const tabs=el("div","gate-tabs");
   for(const [key,title] of [["all","All 36"],["master","G0–G18"],["overlay","Overlay 0–14"],["review","Needs review"]]){
     const btn=el("button","tab",title);btn.type="button";
     btn.setAttribute("aria-pressed",String(state.gateFilter===key));
     btn.addEventListener("click",()=>{state.gateFilter=key;renderDetails();});
     tabs.appendChild(btn);
   }
   body.appendChild(tabs);
   const gates=data.gateDetails||[];
   const visible=gates.filter(x=>state.gateFilter==="all"||
     state.gateFilter==="master"&&MASTER.includes(x.gate)||
     state.gateFilter==="overlay"&&OVERLAY.includes(x.gate)||
     state.gateFilter==="review"&&x.status!=="PASS");
   if(!visible.length){
     body.appendChild(el("div","notice good","Every gate in this view is recorded as PASS in the saved pre-puck evidence."));
   }else{
     const list=el("div","gate-list");
     for(const row of visible)list.appendChild(gateRow(row));
     body.appendChild(list);
   }
 }
 if(path.review){
   const note=el("div","notice"+(path.display!==path.original?" warning":""));
   note.textContent=path.display!==path.original?
      "The later sourced pre-puck path review differs from the original frozen label. The scorer, card ID and revision remain unchanged.":
      "The sourced path review agrees with the original locked label.";
   body.appendChild(note);
   const urls=unique(path.review.sourceUrls).map(u=>link(u)).filter(Boolean);
   if(urls.length){
     const details=el("details","source-details");details.appendChild(el("summary","","Path adjudication sources"));
     const links=el("div","source-links");urls.forEach(a=>links.appendChild(a));
     details.appendChild(links);body.appendChild(details);
   }
 }
 section.appendChild(body);
}
function gateRow(record){
 const details=el("details","gate-row");
 details.dataset.gate=record.gate;
 const summary=el("summary");
 summary.appendChild(el("span","gate-code",
   "#"+(Number.isInteger(record.expectedExecutionIndex)?record.expectedExecutionIndex+1:"?")+" "+record.gate));
 summary.appendChild(el("span","gate-title",EXPLAIN[record.gate]||"Verified source review"));
 summary.appendChild(pill(record.status||"UNKNOWN",statusClass(record.status)));
 summary.appendChild(el("span","gate-chevron","›"));
 details.appendChild(summary);
 const inner=el("div","gate-body");
 const sources=unique((record.sourceIds||[]).filter(x=>
   typeof x==="string"&&x.startsWith("https://")));
 inner.appendChild(el("p","",record.prePuckRecord?
    "Recorded before puck drop · "+(record.evaluatedAt?etTime(record.evaluatedAt):"time unavailable")+
      " · "+sources.length+" attributed source"+(sources.length===1?"":"s"):
    "No matching pre-puck receipt available; this gate is NOT represented as passed."));
 const evidence=record.evidence||{};
 if(record.gate==="G10"&&evidence.notAssistOrFeeder===true){
   const warning=el("div","notice warning",
     "ORIGINAL CARD AUDIT: This older G10 receipt claimed the skater was not an assist/feeder based on historically credited goals alone. It was not proof of tonight's finisher. The frozen original remains unchanged; future engine runs now report this uncertainty accurately.");
   inner.appendChild(warning);
 }
 const summaryBits=el("div","evidence-chips");
 const simple=Object.entries(evidence).filter(([k,v])=>
    (["string","number","boolean"].includes(typeof v))&&v!==null&&
    String(v).length<95);
 for(const [key,val] of simple.slice(0,8))
   summaryBits.appendChild(el("span","evidence-chip",humanKey(key)+": "+String(val)));
 if(summaryBits.childNodes.length)inner.appendChild(summaryBits);
 if(sources.length){
   const sourceList=el("details","source-details");
   sourceList.appendChild(el("summary","","View "+sources.length+" source link"+(sources.length===1?"":"s")));
   const links=el("div","source-links");
   sources.map(u=>link(u)).filter(Boolean).forEach(a=>links.appendChild(a));
   sourceList.appendChild(links);inner.appendChild(sourceList);
 }
 if(Object.keys(evidence).length){
   const raw=el("details","code-details");raw.appendChild(el("summary","","Expand complete gate evidence"));
   const pre=el("pre","raw-json",JSON.stringify(evidence,null,2));
   raw.appendChild(pre);inner.appendChild(raw);
 }
 if(record.appliedPatches?.length){
   const patch=el("p","","Gate policy history: "+record.appliedPatches.join(", "));
   inner.appendChild(patch);
 }
 details.appendChild(inner);return details;
}
function humanKey(s){return String(s).replace(/([a-z])([A-Z])/g,"$1 $2").replace(/[_-]/g," ").replace(/^./,v=>v.toUpperCase());}
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
 if(x.errors?.length)details.appendChild(el("p","",
   "Actual execution errors: "+x.errors.join(" • ")));
 if(x.nonselectedGameResearchNotes?.length)details.appendChild(el("p","",
    "Unselected matchup research: "+x.nonselectedGameResearchNotes.join(" • ")));
 host.appendChild(details);
}
function renderCompleteGateDeck(){
  // All 20 master + 16 overlay steps are displayed identically.
  // This deck is NAVIGATION ONLY; it never changes a Blender decision.
  for(const [id,gates,type] of [
    ["master-gate-deck",MASTER,"master"],
    ["overlay-gate-deck",OVERLAY,"overlay"]
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
      card.appendChild(el("span","mini-gate-symbol",type==="master"?"♠":"◇"));
      card.appendChild(el("span","mini-gate-title",EXPLAIN[gate]||"Source check"));
      card.addEventListener("click",()=>{
        state.gateFilter=type;
        renderDetails();
        const detail=$("leg-detail");
        // Never assert PASS without an actual saved row. The target row
        // includes status, evidence fields and clickable source URLs.
        const row=[...detail.querySelectorAll(".gate-row")].find(
          x=>x.dataset.gate===gate);
        if(row){
          row.open=true;
          row.scrollIntoView({behavior:"smooth",block:"center"});
        }else{
          $("evidence").scrollIntoView({behavior:"smooth",block:"start"});
        }
      });
      holder.appendChild(card);
    }
  }
}
function renderAll(){
 renderPicker();renderHeader();renderCompleteGateDeck();renderCards();renderDetails();
 renderMatchups();renderGrade();renderSeason();renderSystem();
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
 state.gateFilter="all";
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
   seasonSize:season?.officiallyGradedSlates,
   patchCount:season?.verifiedAutomaticGuardPatches?.length,
 });
}
async function boot(){
 $("refresh").addEventListener("click",()=>window.location.reload());
 $("slate-select").addEventListener("change",e=>chooseDate(e.target.value));
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
