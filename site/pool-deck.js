/* TRUE BLENDER · ELITE SURVIVOR DECK
   Display only. Selection, proof and labels come solely from the saved engine.
   A missing original gate receipt is never drawn as a PASS.
*/
(function(root){
"use strict";
let flippedKey=null,visibleDate=null;
const create=(tag,cls,copy)=>{
 const node=document.createElement(tag);
 if(cls)node.className=cls;
 if(copy!==undefined&&copy!==null)node.textContent=String(copy);
 return node;
};
const unique=a=>[...new Set((a||[]).filter(v=>typeof v==="string"&&v.startsWith("https://")))];
const num=v=>typeof v==="number"&&Number.isFinite(v)?String(v):"—";
const safeLabel=v=>String(v||"").replace(/_/g," ").toLowerCase();
function source(anchor,url,label){
 if(typeof url!=="string"||!url.startsWith("https://"))return;
 let parsed;try{parsed=new URL(url)}catch(_){return;}
 if(parsed.protocol!=="https:")return;
 const a=create("a","pool-evidence-link",label);
 a.href=parsed.href;a.target="_blank";a.rel="noopener noreferrer";
 anchor.appendChild(a);
}
function fact(anchor,label,value){
 const line=create("div","pool-fact");
 line.appendChild(create("span","",label));
 line.appendChild(create("strong","",value||"Not reported"));
 anchor.appendChild(line);
}
function toggle(holder,key){
 flippedKey=flippedKey===key?null:key;
 for(const c of holder.children){
   if(!c.classList?.contains("pool-flip-card"))continue;
   const active=c.dataset.cardKey===flippedKey;
   c.classList.toggle("is-flipped",active);
   c.dataset.facing=active?"back":"front";
   const front=c.querySelector(".pool-front-turn");
   const back=c.querySelector(".pool-back-turn");
   if(front)front.setAttribute("aria-expanded",String(active));
   if(back)back.setAttribute("aria-expanded",String(active));
 }
}
function card(holder,g,coreKeys,latest,gates,gateNames,facts){
 const survivor=g.status==="SURVIVOR"&&g.survivor?g.survivor:null;
 const gameKey=String(g.gameId);
 const savedCore=!!survivor&&coreKeys.has(gameKey+":"+String(survivor.playerId));
 const path=survivor?.routeLabel;
 const active=flippedKey===gameKey;
 const card=create("article","pool-flip-card"+(survivor?" qualified":" unqualified")+
     (savedCore?" core-pool-card":"")+(active?" is-flipped":""));
 card.dataset.cardKey=gameKey;
 card.dataset.facing=active?"back":"front";
 const rotator=create("div","pool-flip-inner");
 // Front is an actual, fully clickable button. The back contains separate
 // independent controls and source links, never links nested inside a button.
 const front=create("div","pool-face pool-front");
 const turn=create("button","pool-front-turn");turn.type="button";
 turn.setAttribute("aria-expanded",String(active));
 turn.setAttribute("aria-label",
   "Flip "+(survivor?.player||g.matchup||"game")+" card to inspect original evidence");
 const head=create("div","pool-card-head");
 head.appendChild(create("span","pool-matchup",String(g.matchup||"Matchup unavailable").replace("@"," @ ")));
 head.appendChild(create("span","pool-card-suit","♠"));
 turn.appendChild(head);
 turn.appendChild(create("span","pool-overline",
   savedCore?"IN THE CORE":survivor?"GAME SURVIVOR":"SOURCE REVIEW"));
 const player=create("div","pool-card-player");
 if(survivor){
   player.appendChild(create("strong","pool-player-name",survivor.player));
   player.appendChild(create("span","pool-team",survivor.attackTeam||g.attackTeam||""));
   const route=create("div","pool-route");
   route.appendChild(create("span","pool-path "+(
     path==="TRANSFER"?"transfer":path==="WHO"?"who":"primary"),path||"PATH UNVERIFIED"));
   if(survivor.ownRouteZone)
     route.appendChild(create("span","pool-origin",survivor.ownRouteZone));
   player.appendChild(route);
   player.appendChild(create("span","pool-short-proof",
     num(survivor.ownedGoals)+" goals  ·  "+num(survivor.ownShotsOnGoal)+" on-net shots"));
 }else{
   player.appendChild(create("strong","pool-player-name pool-unresolved","No survivor"));
   player.appendChild(create("span","pool-team",
     g.status==="STARTED_NOT_ELIGIBLE_FOR_NEW_SELECTION"?"GAME FROZEN":"REVIEW IN PROGRESS"));
 }
 turn.appendChild(player);
 turn.appendChild(create("span","pool-turn-tip","VIEW EVIDENCE  ↻"));
 turn.addEventListener("click",()=>toggle(holder,gameKey));
 front.appendChild(turn);
 // Back always renders factual, compact original engine evidence first.
 const back=create("div","pool-face pool-back");
 const top=create("div","pool-back-bar");
 top.appendChild(create("strong","",survivor?.player||String(g.matchup||"Matchup")));
 const backTurn=create("button","pool-back-turn","↶ FRONT");
 backTurn.type="button";
 backTurn.setAttribute("aria-label","Turn "+(survivor?.player||g.matchup||"game")+" back to front");
 backTurn.setAttribute("aria-expanded",String(active));
 backTurn.addEventListener("click",()=>toggle(holder,gameKey));
 top.appendChild(backTurn);back.appendChild(top);
 const info=create("div","pool-back-content");
 if(survivor){
   info.appendChild(create("p","pool-back-subtitle","REAL SCORING PATH · "+String(latest?.gameSurvivorDisplayStage||latest?.stage||"STAGE UNREPORTED")));
   fact(info,"G0 · Target goalie",String(survivor.goalieId||"Unreported")+
       " · "+String(survivor.goalieStatus||"Unconfirmed"));
   fact(info,"G4/G5 · Own release",String(survivor.ownRouteZone||"Not recorded")+
       " · "+num(survivor.ownedGoals)+" goals · "+
       num(survivor.ownShotsOnGoal)+" shots on net");
   const deployment=survivor.deployment||{};
   fact(info,"G6 · Deployment",(deployment.EV||"EV not reported")+
     (deployment.powerPlayUnit?" · PP"+deployment.powerPlayUnit:"")+
     (deployment.status?" · "+deployment.status:""));
   const defense=survivor.independentOpponentDefense||{};
   if(typeof defense.attemptsAgainst==="number"){
     fact(info,"G9 · Defense",num(defense.attemptsAgainst)+" attempts · "+
       num(defense.onNetShotsAgainst)+" on-net · "+
       num(defense.gameCount)+" games");
   }
   fact(info,"G16 · Cross-game",safeLabel(g.g16Decision||"no cross-game decision reported"));
   const pathProof=survivor.pathClassificationEvidence||{};
   if(pathProof.rationale)
     info.appendChild(create("p","pool-back-reason",pathProof.rationale));
   const key=gameKey+":"+String(survivor.playerId);
   const receipts=latest?.gameSurvivorGateReceipts?.[key];
   if(Array.isArray(receipts)&&receipts.length){
     info.appendChild(create("strong","pool-gate-heading","ORIGINAL G0–G18 · TAP TO INSPECT"));
     const byGate=new Map(receipts.map(rec=>[rec.gate,rec]));
     for(const gate of gates){
       const rec=byGate.get(gate)||{gate,status:"NOT_RECORDED",
         prePuckRecord:false,evidence:{},sourceIds:[]};
       const proof=create("details","pool-gate-proof");
       proof.dataset.gate=gate;
       const summary=create("summary","");
       summary.appendChild(create("span","",gate));
       const passed=rec.status==="PASS"&&rec.prePuckRecord===true;
       summary.appendChild(create("span","pool-gate-verdict"+(passed?" passed":" pending"),
         passed?"✓":safeLabel(rec.status)));
       proof.appendChild(summary);
       proof.appendChild(create("p","",facts.explanation(rec)));
       if(Array.isArray(rec.originalFunctions)&&rec.originalFunctions.length){
         proof.appendChild(create("p","pool-function-proof",
           rec.originalFunctions.map(f=>String(f.step)+" · "+String(f.status)).join(" · ")));
       }
       const refs=create("div","pool-gate-links");
       unique(rec.sourceIds).forEach((u,i)=>source(refs,u,"Source "+(i+1)));
       proof.appendChild(refs);
       info.appendChild(proof);
     }
   }else{
     info.appendChild(create("p","pool-receipt-pending",
       "Full original gate receipt not published in this feed. The dated scoring-route evidence above remains inspectable; missing gate details are not marked passed."));
   }
   const links=create("div","pool-evidence-sources");
   links.appendChild(create("strong","","SOURCES"));
   unique([survivor.routeSource,survivor.goalieSourceUrl,
     survivor.defenseSourceUrl,survivor.deploymentSourceUrl,
     ...(pathProof.sourceUrls||[])]).slice(0,12).forEach((url,i)=>
       source(links,url,"Evidence "+(i+1)));
   info.appendChild(links);
 }else{
   info.appendChild(create("p","pool-receipt-pending",
     g.status==="STARTED_NOT_ELIGIBLE_FOR_NEW_SELECTION"?
       "This game is frozen after puck drop.":
       "No source-qualified game survivor has been published."));
   if(g.currentSourceBlocker)
      fact(info,"Current source blocker",
        g.currentSourceBlocker+" · "+(gateNames[g.currentSourceBlocker]||"unresolved"));
   const failures=g.firstNonPassGateCounts||{};
   for(const [gate,count] of Object.entries(failures))
     fact(info,gate,String(count)+" skater evaluations");
 }
 back.appendChild(info);
 rotator.appendChild(front);rotator.appendChild(back);card.appendChild(rotator);
 holder.appendChild(card);
}
function render({holder,games,coreLegs,latest,gates,gateNames,facts,date}){
 if(date!==visibleDate){flippedKey=null;visibleDate=date;}
 holder.replaceChildren();
 if(!games?.length){
   holder.appendChild(create("p","pool-empty","No saved game-survivor data for this slate."));
   return;
 }
 const count=games.filter(g=>g.status==="SURVIVOR"&&g.survivor).length;
 const coreKeys=new Set((coreLegs||[]).map(x=>
   String(x.gameId)+":"+String(x.playerId)));
 // Saved Core identity is independent of a newer, incomplete per-game run.
 // Never erase the actual saved Core count because its latest pool is empty.
 const core=(coreLegs||[]).length;
 const stats=create("div","pool-stat-strip");
 for(const [value,label] of [[count+" / "+games.length,"SURVIVORS"],
     [core,"CORE SAVED"],[games.length-count,"IN REVIEW"]]){
   const item=create("div","pool-stat");
   item.appendChild(create("strong","",value));
   item.appendChild(create("span","",label));
   stats.appendChild(item);
 }
 const cohort=latest?.gameSurvivorDisplayProvenance;
 if(cohort?.origin==="LAST_FULLY_SOURCE_CERTIFIED_PREPUCK_COHORT"){
   const note=create("div","pool-snapshot-note",
     "LAST VERIFIED "+String(cohort.sourceStage||"PROJECTED")+" POOL · NEWER REVIEW NOT YET CERTIFIED");
   stats.appendChild(note);
 }
 holder.appendChild(stats);
 for(const g of games)card(holder,g,coreKeys,latest,gates,gateNames,facts);
}
const api={render};
if(typeof module!=="undefined"&&module.exports)module.exports=api;
root.ElitePool=api;
})(typeof window!=="undefined"?window:globalThis);
