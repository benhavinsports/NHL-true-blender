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
 heading.appendChild(create("strong","","ORIGINAL G0–G18 EVIDENCE"));
 heading.appendChild(create("span","","20 decisions · original order"));
 area.appendChild(heading);
 if(!Array.isArray(receipts)||!receipts.length){
  area.appendChild(create("p","scout-missing",
    "Original gate receipts are unavailable in this saved feed. Missing evidence is never displayed as passed."));
  return;
 }
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
 const head=create("div","scout-path-strip");
 head.appendChild(create("span","scout-path-type",String(path||"PATH NOT VERIFIED")));
 head.appendChild(create("strong","",useOrigin));
 head.appendChild(create("span","scout-path-caption","Historical rink shot origin · not a forecast"));
 body.appendChild(head);
 const kpis=create("div","scout-metrics");
 metric(kpis,"G0","OPPOSING GOALIE",useGoalie?"#"+useGoalie:"Not reported",useStatus);
 metric(kpis,"G4","CREDITED GOALS",numbers(useGoals)?useGoals:"—","In selected origin");
 metric(kpis,"G4","ON-NET SHOTS",numbers(useShots)?useShots:"—","Own shots in origin");
 metric(kpis,"G6","DEPLOYMENT",
   [ev.EV||ev.line?"EV "+(ev.EV||ev.line):null,
    ev.powerPlayUnit?"PP"+ev.powerPlayUnit:null].filter(Boolean).join(" / ")||"Not reported",
   ev.status||"Source stage not reported");
 body.appendChild(kpis);
 if(numbers(useGoals)&&numbers(useShots)&&useShots>0&&useGoals>=0&&useGoals<=useShots){
  const row=create("div","scout-conversion");
  const text=create("div","scout-conversion-label");
  text.appendChild(create("span","","OBSERVED AREA GOALS / SHOTS"));
  text.appendChild(create("strong","",useGoals+" / "+useShots));
  row.appendChild(text);
  const track=create("div","scout-conversion-track");
  const fill=create("span","scout-conversion-fill");
  fill.style.width=(100*useGoals/useShots).toFixed(2)+"%";
  track.appendChild(fill);row.appendChild(track);
  row.appendChild(create("p","",
    "Historical recorded totals only. This bar does not predict a goal."));
  body.appendChild(row);
 }
 const context=create("div","scout-context");
 context.appendChild(create("h4","","MATCHUP INTELLIGENCE"));
 if(numbers(concede.attemptsAgainst)){
  section(context,"DEFENSIVE COVERAGE",
    concede.attemptsAgainst+" observed attempts · "+
    (numbers(concede.onNetShotsAgainst)?concede.onNetShotsAgainst+" on-net · ":"")+
    (numbers(concede.gameCount)?concede.gameCount+" games":"sample unreported"));
 }else section(context,"DEFENSIVE COVERAGE","Source-specific concession count not reported");
 const g105=byGate.get("G10.5");
 const g17=byGate.get("G17");
 if(g105)section(context,"RECIPIENT SEPARATION",
   status(g105).ok?"Direct teammate routes reviewed":"Review not source-certified");
 if(g17)section(context,"CONTRADICTION CHECK",
   status(g17).ok?"Recorded cross-source review complete":"Unresolved in saved evidence");
 if(g16Decision)section(context,"G16 · CROSS-GAME COMPETITION",
   String(g16Decision).replace(/_/g," ").toLowerCase());
 body.appendChild(context);
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
