/* TRUE BLENDER — PRESENTATION ONLY.
   Shared collector photographs and source-derived professional scouting backs.
   No scorer selection, odds, scoring probability or gate outcome is computed here.
*/
(function(root){
"use strict";
const create=(tag,cls,value)=>{
 const node=document.createElement(tag);
 if(cls)node.className=cls;
 if(value!==undefined&&value!==null)node.textContent=String(value);
 return node;
};
const validTeam=x=>typeof x==="string"&&/^[A-Z]{3}$/.test(x);
const numbers=x=>typeof x==="number"&&Number.isFinite(x);
const show=x=>x===null||x===undefined||x===""?"Not reported":String(x);
const urls=a=>[...new Set((a||[]).filter(u=>typeof u==="string"&&u.startsWith("https://")))];
const explain=(facts,rec)=>facts&&typeof facts.explanation==="function"?
 facts.explanation(rec):"Original gate decision is available in saved evidence.";
function link(url,label){
 try{
  const parsed=new URL(url);
  if(parsed.protocol!=="https:")return null;
  const a=create("a","scout-source",label);
  a.href=parsed.href;a.target="_blank";a.rel="noopener noreferrer";
  return a;
 }catch(_){return null;}
}
function photo({player,playerId,team,matchup,date,preferPortrait=false}){
 const art=create("div","card-illustration collector-art survivor-collector-art");
 art.appendChild(create("span","collector-foil-rings"));
 const pid=String(playerId||"");
 const yr=Number(String(date||"").slice(0,4));
 const season=Number.isInteger(yr)&&yr>=2020&&yr<=2040?String(yr)+String(yr+1):"20262027";
 const teams=[team,...String(matchup||"").split("@")]
   .filter(validTeam).filter((x,i,a)=>a.indexOf(x)===i);
 const action=["https://assets.nhle.com/mugs/actionshots/1296x729/"+pid+".jpg","action"];
 const portraits=teams.map(t=>[
   "https://assets.nhle.com/mugs/nhl/"+season+"/"+t+"/"+pid+".png","headshot"]);
 // A 16:9 actionshot fills a tiny portrait card with an unrecognizable
 // blurred arena. Survivor cards try the player's NHL headshot first and
 // keep official actionshots as fallback rather than forcing a crop.
 const options=/^\d{7,8}$/.test(pid)?
   (preferPortrait?[...portraits,action]:[action,...portraits]):[];
 if(options.length){
  let index=0;
  const img=create("img","collector-photo");
  img.alt=String(player||"Player")+" NHL player photograph";
  img.loading="lazy";img.decoding="async";img.draggable=false;
  img.addEventListener("load",()=>{
   art.classList.add("has-photo");
   art.classList.toggle("is-headshot",options[index][1]==="headshot");
  });
  img.addEventListener("error",()=>{
   index++;
   if(index<options.length)img.src=options[index][0];
   else {img.remove();art.classList.add("photo-unavailable");}
  });
  img.src=options[0][0];art.appendChild(img);
 }else art.classList.add("photo-unavailable");
 const shade=create("span","collector-photo-shade");
 shade.setAttribute("aria-hidden","true");art.appendChild(shade);
 if(teams.length){
  const crest=create("img","collector-team-crest");
  crest.alt="";crest.loading="lazy";
  crest.src="https://assets.nhle.com/logos/nhl/svg/"+teams[0]+"_light.svg";
  crest.addEventListener("error",()=>crest.remove());art.appendChild(crest);
 }
 const initials=create("span","collector-fallback",String(player||"")
   .split(/\s+/).map(x=>x[0]).join("").slice(0,2).toUpperCase());
 initials.setAttribute("aria-hidden","true");art.appendChild(initials);
 return art;
}
function metric(area,reference,title,value,note){
 const card=create("div","scout-metric");
 card.appendChild(create("span","scout-metric-ref",reference));
 card.appendChild(create("span","scout-metric-title",title));
 card.appendChild(create("strong","scout-metric-value",value));
 if(note)card.appendChild(create("span","scout-metric-note",note));
 area.appendChild(card);
}
function section(area,label,body){
 const row=create("div","scout-context-row");
 row.appendChild(create("span","scout-context-label",label));
 row.appendChild(create("strong","scout-context-value",body));
 area.appendChild(row);
}
// Source-to-visual mapping. The illustrated areas are schematic categories,
// NOT exact NHL EDGE event coordinates and never goalie anatomy.
function normalizeZone(zone){
 return String(zone||"").toLowerCase().replace(/[^a-z]/g,"").replace("centerpoint","point");
}
function rinkGraphic(origin){
 const field=create("div","scout-rink-panel");
 const header=create("div","scout-visual-label");
 header.appendChild(create("span","","SHOT ORIGIN / SCHEMATIC"));
 header.appendChild(create("span","scout-visual-index","G4 · G5"));
 field.appendChild(header);
 const rink=create("div","scout-rink-map");
 rink.setAttribute("aria-label","Schematic rink origin map. Source lane: "+show(origin));
 const rinkNet=create("span","scout-rink-net","GOAL");
 rink.appendChild(rinkNet);
 const zones=[
  ["L POINT","lpoint"],["POINT","point"],["R POINT","rpoint"],
  ["L CIRCLE","lcircle"],["HIGH SLOT","highslot"],["R CIRCLE","rcircle"],
  ["","empty-l"],["LOW SLOT","lowslot"],["","empty-r"]
 ];
 const originKey=normalizeZone(origin);
 let matched=false;
 for(const [title,key] of zones){
  const active=!!title&&originKey===key;
  const marker=create("span","scout-rink-zone"+(active?" active":"")+
    (!title?" is-empty":""),title);
  if(active){matched=true;marker.setAttribute("aria-current","true");}
  rink.appendChild(marker);
 }
 field.appendChild(rink);
 const foot=create("div","scout-rink-foot");
 foot.appendChild(create("span","",matched?"OBSERVED AREA":"AREA NOT PLOTTED"));
 foot.appendChild(create("strong","",show(origin)));
 field.appendChild(foot);
 field.appendChild(create("p","scout-chart-disclaimer",
   "Category diagram · not shot coordinates or goalie anatomy"));
 return field;
}
function barPanel({goalRate,peerGoalRate,goals,games,origin}){
 const area=create("section","scout-pressure-card");
 const header=create("div","scout-module-title");
 header.appendChild(create("span","","OPPONENT DEFENSIVE GOALS CONCEDED"));
 header.appendChild(create("span","scout-visual-index","G9"));
 area.appendChild(header);
 area.appendChild(create("p","scout-module-sub",
   "Observed goals allowed by the defending team from "+show(origin)+
   " · historical rink scoring origin, not the goalmouth"));
 if(numbers(goalRate)&&goalRate>=0&&numbers(peerGoalRate)&&peerGoalRate>=0){
  const max=Math.max(goalRate,peerGoalRate,0.01);
  const makeRow=(label,value,kind)=>{
   const row=create("div","scout-compare-row");
   const rowTitle=create("div","scout-compare-head");
   rowTitle.appendChild(create("span","",label));
   rowTitle.appendChild(create("strong","",value.toFixed(3)+" goals / game"));
   row.appendChild(rowTitle);
   const track=create("div","scout-compare-track");
   const fill=create("span","scout-compare-fill "+kind);
   fill.style.width=(100*value/max).toFixed(1)+"%";
   track.appendChild(fill);row.appendChild(track);area.appendChild(row);
  };
  makeRow("OPPONENT GOALS CONCEDED",goalRate,"concession");
  makeRow("OTHER-TEAM GOAL MEDIAN",peerGoalRate,"peer");
  area.appendChild(create("p","scout-chart-disclaimer",
   goalRate>peerGoalRate?
   "Elevated goals conceded from this area compared with peers.":
   "This area is NOT elevated above the peer goal-concession median. G9 records an independent defensive review, not an additional goal scorer pick."));
 }else area.appendChild(create("div","scout-unreported",
   "Opponent defensive GOALS conceded by origin were not included in this saved excerpt"));
 const footer=create("div","scout-pressure-footer");
 footer.appendChild(create("strong","",numbers(goals)?goals+" goals against":"Goals unreported"));
 footer.appendChild(create("span","",numbers(games)?games+" games reviewed":"Game sample unreported"));
 area.appendChild(footer);
 area.appendChild(create("p","scout-chart-disclaimer",
   "No shot-attempt ranking. Shooter's actual goal area versus the goalie's conceded-goal area is established separately at G5."));
 return area;
}
function sideIntel(title,value,sub,ref){
 const card=create("div","scout-intel-tile");
 const heading=create("div","scout-intel-heading");
 heading.appendChild(create("span","",title));
 heading.appendChild(create("b","",ref));
 card.appendChild(heading);
 card.appendChild(create("strong","scout-intel-value",value));
 card.appendChild(create("span","scout-intel-sub",sub));
 return card;
}
function status(rec){
 if(!rec)return {ok:false,text:"NO SOURCE RECEIPT"};
 if(rec.status==="PASS"&&rec.prePuckRecord===true)return {ok:true,text:"SOURCE VERIFIED"};
 if(rec.status==="PASS")return {ok:false,text:"TIMING UNVERIFIED"};
 return {ok:false,text:String(rec.status||"NOT_RECORDED").replace(/_/g," ")};
}
const GROUPS=[
 {name:"01 · GOALIE & ATTACKING ROUTE",gates:["G0","G1","G2","G3","G4","G5"]},
 {name:"02 · DEPLOYMENT & RECIPIENT",gates:["G6","G7","G8","G9","G10","G10.5"]},
 {name:"03 · SCORING SOURCE PROOF",gates:["G11","G12","G13","G14","G15"]},
 {name:"04 · FINAL COMPETITION & REVIEW",gates:["G16","G17","G18"]}
];
function gateRows(area,receipts,gates,gateNames,facts){
 const byGate=new Map((receipts||[]).map(x=>[x.gate,x]));
 const heading=create("div","scout-section-heading");
 heading.appendChild(create("strong","","GATE EVIDENCE"));
 heading.appendChild(create("span","","Original G0–G18 · 20 checkpoints"));
 area.appendChild(heading);
 if(!Array.isArray(receipts)||!receipts.length){
  area.appendChild(create("p","scout-missing",
    "Original gate receipts are unavailable in this saved feed. Missing evidence is never displayed as passed."));
  return;
 }
 // A visual 20-gate board belongs ABOVE the receipts; no duplicated
 // evidence and no synthetic verdict. Tap a chip to open its real record.
 const gateIndex=create("nav","scout-gate-index");
 gateIndex.setAttribute("aria-label","Jump to original gate evidence");
 const gateTargets=new Map();
 for(const group of GROUPS){
  for(const gate of group.gates){
   if(Array.isArray(gates)&&!gates.includes(gate))continue;
   const rec=byGate.get(gate);
   const verdict=status(rec);
   const chip=create("button","scout-gate-chip "+(verdict.ok?"is-pass":"is-unresolved"),gate);
   chip.type="button";
   chip.setAttribute("aria-label",gate+" · "+(gateNames?.[gate]||"original gate")+
      " · "+verdict.text);
   const indicator=create("span","scout-chip-dot",verdict.ok?"✓":"·");
   chip.appendChild(indicator);
   chip.addEventListener("click",()=>{
     const target=gateTargets.get(gate);
     if(!target)return;
     target.open=true;
     target.scrollIntoView?.({behavior:"smooth",block:"nearest"});
   });
   gateIndex.appendChild(chip);
  }
 }
 area.appendChild(gateIndex);
 const gateCounts=create("div","scout-gate-summary-line");
 const certified=GROUPS.flatMap(g=>g.gates).filter(g=>{
   const rec=byGate.get(g);return status(rec).ok;
 }).length;
 gateCounts.appendChild(create("strong","",certified+" / 20"));
 gateCounts.appendChild(create("span","",
   "Source-verified original pre-puck gate receipts · tap a number to inspect"));
 area.appendChild(gateCounts);
 for(const group of GROUPS){
  const groupBox=create("section","scout-gate-group");
  groupBox.appendChild(create("h4","",group.name));
  for(const gate of group.gates){
   if(Array.isArray(gates)&&!gates.includes(gate))continue;
   const rec=byGate.get(gate)||{gate,status:"NOT_RECORDED",
      prePuckRecord:false,evidence:{},sourceIds:[]};
   const verdict=status(rec);
   const detail=create("details","scout-gate flip-gate-row pool-gate-proof "+
       (verdict.ok?"verified":"unresolved"));
   detail.dataset.gate=gate;
   gateTargets.set(gate,detail);
   const sum=create("summary","scout-gate-summary");
   sum.appendChild(create("span","scout-gate-key",gate));
   const textWrap=create("span","scout-gate-labels");
   textWrap.appendChild(create("strong","",gateNames?.[gate]||"Original gate"));
   const description=explain(facts,rec);
   textWrap.appendChild(create("span","scout-gate-teaser",description));
   sum.appendChild(textWrap);
   sum.appendChild(create("span","scout-gate-verdict "+(verdict.ok?"is-pass":"is-review"),
     verdict.ok?"✓":verdict.text));
   detail.appendChild(sum);
   const reveal=create("div","scout-gate-reveal");
   reveal.appendChild(create("p","scout-gate-full-proof",description));
   const originals=Array.isArray(rec.evidence?.originalFunctionEvidence)?
     rec.evidence.originalFunctionEvidence:Array.isArray(rec.originalFunctions)?
       rec.originalFunctions:[];
   if(originals.length){
    const steps=create("div","scout-original-functions");
    steps.appendChild(create("span","scout-mini-heading","RECORDED FUNCTIONS"));
    for(const fn of originals){
     const line=create("div","flip-function-line scout-original-function");
     line.appendChild(create("strong","",String(fn.step||"Step")+" · "+
       (gateNames?.[fn.step]||"Original function")));
     const factsItems=Object.entries(fn.evidence||{}).filter(([k,v])=>
       !["independentOverlayEvaluation","checkedBeforeG18","masterGateVerdictCopied","nonblocking"].includes(k)&&
       (typeof v==="number"||typeof v==="boolean"||typeof v==="string")&&
       String(v).length<48).slice(0,3);
     if(factsItems.length)line.appendChild(create("p","",
       factsItems.map(([k,v])=>k.replace(/([a-z])([A-Z])/g,"$1 $2")+": "+v).join(" · ")));
     else if(fn.status||fn.disposition)line.appendChild(
       create("p","",String(fn.status||fn.disposition)));
     steps.appendChild(line);
    }
    reveal.appendChild(steps);
   }
   const sources=create("div","scout-gate-sources flip-gate-sources pool-gate-links");
   urls(rec.sourceIds).forEach((u,i)=>{
    const a=link(u,"Source "+(i+1)+" ↗");if(a)sources.appendChild(a);
   });
   reveal.appendChild(sources);detail.appendChild(reveal);
   groupBox.appendChild(detail);
  }
  area.appendChild(groupBox);
 }
}
function report({
 player,team,matchup,stage,path,goalieId,goalieStatus,origin,
 ownGoals,ownShots,defense,deployment,g16Decision,receipts,
 gateNames,facts,sources,close,missingReason
}){
 const byGate=new Map((receipts||[]).map(x=>[x.gate,x]));
 const fromGate=gate=>byGate.get(gate)?.evidence||{};
 const release=fromGate("G4").ownRelease||{};
 const goalie=fromGate("G0");
 const useGoals=numbers(release.ownedGoals)?release.ownedGoals:ownGoals;
 const useShots=numbers(release.attempts)?release.attempts:ownShots;
 const useOrigin=release.zone||origin||"Not recorded";
 const useGoalie=goalie.targetGoalie||goalieId;
 const useStatus=goalie.branchStatus||goalieStatus||"Not confirmed";
 const ev=fromGate("G6").deployment||deployment||{};
 const concede=fromGate("G9").zoneConcessionEvidence||defense||{};
 const report=create("div","scout-report");
 const header=create("div","scout-header");
 const title=create("div","scout-title");
 title.appendChild(create("span","scout-eyebrow","TRUE BLENDER / SCOUTING INTELLIGENCE"));
 title.appendChild(create("strong","",player||matchup||"Unresolved matchup"));
 title.appendChild(create("span","scout-subtitle",
   [team,matchup,String(stage||"UNVERIFIED")+" SOURCE"].filter(Boolean).join(" · ")));
 header.appendChild(title);
 const dismiss=create("button","scout-dismiss pool-back-turn","CLOSE ✕");
 dismiss.type="button";dismiss.setAttribute("aria-label","Return to front of "+(player||matchup||"card"));
 if(typeof close==="function")dismiss.addEventListener("click",close);
 header.appendChild(dismiss);report.appendChild(header);
 const body=create("div","scout-body pool-back-content");
 if(missingReason){
  body.appendChild(create("div","scout-missing",missingReason));
  report.appendChild(body);return report;
 }
 // LIVE PRODUCT LAYOUT, historical data only: an at-a-glance dossier instead
 // of four generic boxes. Every graphic is linked to its original source.
 const intro=create("div","scout-report-intro");
 const eyebrow=create("div","scout-report-eyebrow");
 eyebrow.appendChild(create("span","","01 / MATCHUP SCOUTING"));
 eyebrow.appendChild(create("span","scout-stage-indicator",String(stage||"UNVERIFIED")+" SOURCE"));
 intro.appendChild(eyebrow);
 const headline=create("div","scout-report-headline");
 headline.appendChild(create("strong","",show(useOrigin)));
 headline.appendChild(create("span","",String(path||"PATH UNVERIFIED")));
 intro.appendChild(headline);
 intro.appendChild(create("p","scout-report-deck",
   "Measured shooting origin versus opposing goalie and defensive coverage"));
 body.appendChild(intro);
 const visual=create("div","scout-visual-layout");
 visual.appendChild(rinkGraphic(useOrigin));
 const shot=create("section","scout-shot-panel");
 const shotHeader=create("div","scout-module-title");
 shotHeader.appendChild(create("span","","SHOOTER · RECORDED ORIGIN"));
 shotHeader.appendChild(create("span","scout-visual-index","G4"));
 shot.appendChild(shotHeader);
 const highlight=create("div","scout-shot-number");
 highlight.appendChild(create("strong","",numbers(useGoals)?useGoals:"—"));
 highlight.appendChild(create("span","","/ "+(numbers(useShots)?useShots:"—")));
 shot.appendChild(highlight);
 shot.appendChild(create("p","scout-shot-caption",
   "Credited goals / own on-net shots from this origin"));
 if(numbers(useGoals)&&numbers(useShots)&&useShots>0&&useGoals>=0&&useGoals<=useShots){
  const percent=100*useGoals/useShots;
  const radial=create("div","scout-shot-ring");
  radial.style.background="conic-gradient(#83d6c4 0% "+
    percent.toFixed(2)+"%,#2a4355 "+percent.toFixed(2)+"% 100%)";
  const center=create("div","scout-shot-ring-center");
  center.appendChild(create("strong","",percent.toFixed(1)+"%"));
  center.appendChild(create("span","","historical goal share"));
  radial.appendChild(center);shot.appendChild(radial);
 }
 shot.appendChild(create("p","scout-chart-disclaimer",
   "Past credited goals per on-net shot. Never a prediction."));
 visual.appendChild(shot);body.appendChild(visual);
 const matchupDashboard=create("section","scout-dashboard-module");
 const matchHead=create("div","scout-module-title");
 matchHead.appendChild(create("span","","02 / GOALIE & DEPLOYMENT"));
 matchHead.appendChild(create("span","scout-visual-index","G0 · G3 · G6"));
 matchupDashboard.appendChild(matchHead);
 const compare=create("div","scout-intel-grid");
 const weak=goalie.weakZones?.[useOrigin]||fromGate("G3").goalieWeakZones?.[useOrigin]||{};
 const goalieDetail=[
    useStatus,
    numbers(weak.goalsAgainst)&&numbers(weak.shotsAgainst)?
      weak.goalsAgainst+" allowed / "+weak.shotsAgainst+" on-net in origin":null
   ].filter(Boolean).join(" · ");
 compare.appendChild(sideIntel("OPPOSING GOALIE",
   useGoalie?"#"+useGoalie:"Not reported",goalieDetail,"G0"));
 const deploymentSummary=[
   ev.EV?"EV "+ev.EV:typeof ev.line==="number"?"Line "+ev.line:null,
   ev.powerPlayUnit?"PP"+ev.powerPlayUnit:null
 ].filter(Boolean).join(" · ");
 compare.appendChild(sideIntel("SKATER DEPLOYMENT",
   deploymentSummary||"Not reported",String(ev.status||"Source unreported"),"G6"));
 matchupDashboard.appendChild(compare);
 body.appendChild(matchupDashboard);
 const goalRate=numbers(concede.goalsAgainstPerGame)?concede.goalsAgainstPerGame:null;
 const peerGoalRate=numbers(concede.peerMedianGoalsAgainstPerGame)?
   concede.peerMedianGoalsAgainstPerGame:null;
 body.appendChild(barPanel({
   goalRate,peerGoalRate,goals:concede.goalsAgainst,
   games:concede.gameCount,origin:useOrigin
 }));
 const review=create("section","scout-review-section");
 const revHeader=create("div","scout-module-title");
 revHeader.appendChild(create("span","","03 / RECIPIENT & COMPETITION"));
 revHeader.appendChild(create("span","scout-visual-index","G10.5 · G16 · G17"));
 review.appendChild(revHeader);
 const reviews=create("div","scout-review-grid");
 const g105=byGate.get("G10.5"),g17=byGate.get("G17");
 const compared=fromGate("G10.5").comparisonRows;
 const separation=status(g105).ok;
 reviews.appendChild(sideIntel("RECIPIENT REVIEW",
   separation&&Array.isArray(compared)?String(compared.length)+" rival paths":
     separation?"Source reviewed":"Unverified",
   separation?"Teammate scoring lanes compared":"Original gate check needed","G10.5"));
 const contradiction=status(g17).ok;
 reviews.appendChild(sideIntel("CONTRADICTIONS",
   contradiction?"Reviewed":"Unresolved",
   contradiction?"Recorded counterevidence examined":"Saved verification unavailable","G17"));
 const decision=String(g16Decision||fromGate("G18").G16FinalistDecision||"").replace(/_/g," ");
 const g16Review=byGate.get("G16");
 reviews.appendChild(sideIntel("CROSS-GAME",
   decision?decision.charAt(0).toUpperCase()+decision.slice(1).toLowerCase():
     status(g16Review).ok?"PASS · reviewed":"Review not in source",
   status(g16Review).ok?
    "Original G16 recipient competition passed; no distinct cross-game ranking recorded":
    "Original G16 competition receipt unavailable","G16"));
 review.appendChild(reviews);
 body.appendChild(review);
 gateRows(body,receipts,null,gateNames,facts);
 const raw=create("div","scout-global-sources");
 const links=urls(sources);
 if(links.length){
  raw.appendChild(create("span","scout-mini-heading","SCORING PATH SOURCES"));
  links.slice(0,12).forEach((u,i)=>{const a=link(u,"Evidence "+(i+1)+" ↗");if(a)raw.appendChild(a);});
  body.appendChild(raw);
 }
 report.appendChild(body);return report;
}
const api={photo,report};
if(typeof module!=="undefined"&&module.exports)module.exports=api;
root.NHLScouting=api;
})(typeof window!=="undefined"?window:globalThis);
