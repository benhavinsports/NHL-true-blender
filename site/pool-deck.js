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
 // An opened scouting record expands above the small mobile grid.
 // A single flip remains the sole interaction; no editing or selection.
 document.body?.classList?.toggle("pool-card-open",Boolean(flippedKey));
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
function card(holder,g,coreKeys,latest,gates,gateNames,facts,date){
 const survivor=g.status==="SURVIVOR"&&g.survivor?g.survivor:null;
 const gameKey=String(g.gameId);
 const savedCore=!!survivor&&coreKeys.has(gameKey+":"+String(survivor.playerId));
 const path=survivor?.routeLabel;
 const active=flippedKey===gameKey;
 const card=create("article","pool-flip-card pool-collector-card"+
    (survivor?" qualified":" unqualified")+
    (savedCore?" core-pool-card":"")+(active?" is-flipped":""));
 card.dataset.cardKey=gameKey;card.dataset.facing=active?"back":"front";
 const rotator=create("div","pool-flip-inner");
 const front=create("div","pool-face pool-front");
 // A single accessible button covers the collector-card FRONT. The reverse
 // contains independent focusable evidence controls (not nested buttons).
 const turn=create("button","pool-front-turn");turn.type="button";
 turn.setAttribute("aria-expanded",String(active));
 turn.setAttribute("aria-label","Flip "+(survivor?.player||g.matchup||"game")+
    " collector card to open scouting evidence");
 if(survivor){
   turn.appendChild(NHLScouting.photo({
     player:survivor.player,playerId:survivor.playerId,
     team:survivor.attackTeam||g.attackTeam,matchup:g.matchup,date
   }));
 }
 const head=create("div","pool-card-head collector-pool-masthead");
 head.appendChild(create("span","pool-matchup",
   String(g.matchup||"Matchup unavailable").replace("@"," @ ")));
 head.appendChild(create("span","pool-card-series",
   savedCore?"CORE MEMBER":"NHL · GAME SURVIVOR"));
 turn.appendChild(head);
 const player=create("div","pool-card-player collector-pool-nameplate");
 if(survivor){
   player.appendChild(create("span","pool-team",survivor.attackTeam||g.attackTeam||""));
   player.appendChild(create("strong","pool-player-name",survivor.player));
   const route=create("div","pool-route");
   route.appendChild(create("span","pool-path "+
     (path==="TRANSFER"?"transfer":path==="WHO"?"who":"primary"),
     path||"PATH UNVERIFIED"));
   if(survivor.ownRouteZone)
     route.appendChild(create("span","pool-origin",survivor.ownRouteZone));
   player.appendChild(route);
   player.appendChild(create("span","pool-short-proof",
     num(survivor.ownedGoals)+" credited goals · "+
     num(survivor.ownShotsOnGoal)+" on-net shots"));
 }else{
   player.appendChild(create("strong","pool-player-name pool-unresolved","No survivor"));
   player.appendChild(create("span","pool-team",
     g.status==="STARTED_NOT_ELIGIBLE_FOR_NEW_SELECTION"?
     "GAME FROZEN":"SOURCE REVIEW OPEN"));
 }
 turn.appendChild(player);
 turn.appendChild(create("span","pool-turn-tip",
   "FLIP · SCOUTING REPORT   ↗"));
 turn.addEventListener("click",()=>toggle(holder,gameKey));
 front.appendChild(turn);
 const back=create("div","pool-face pool-back");
 const pathProof=survivor?.pathClassificationEvidence||{};
 const receipts=survivor?latest?.gameSurvivorGateReceipts?.[
    gameKey+":"+String(survivor.playerId)]:null;
 back.appendChild(NHLScouting.report({
    player:survivor?.player||null,
    team:survivor?.attackTeam||g.attackTeam,
    matchup:g.matchup,
    stage:latest?.gameSurvivorDisplayStage||latest?.stage,
    path:path,
    goalieId:survivor?.goalieId,
    goalieStatus:survivor?.goalieStatus,
    origin:survivor?.ownRouteZone,
    ownGoals:survivor?.ownedGoals,
    ownShots:survivor?.ownShotsOnGoal,
    defense:survivor?.independentOpponentDefense,
    deployment:survivor?.deployment,
    g16Decision:g.g16Decision,
    receipts,
    gateNames,facts,
    sources:survivor?unique([
      survivor.routeSource,survivor.goalieSourceUrl,
      survivor.defenseSourceUrl,survivor.deploymentSourceUrl,
      ...(pathProof.sourceUrls||[])
    ]):[],
    close:()=>toggle(holder,gameKey),
    missingReason:survivor?null:
      g.status==="STARTED_NOT_ELIGIBLE_FOR_NEW_SELECTION"?
        "This game is frozen after puck drop. No new scorer is being selected.":
        "No original gate-qualified survivor has been published for this matchup."
 }));
 rotator.appendChild(front);rotator.appendChild(back);
 card.appendChild(rotator);holder.appendChild(card);
}
function render({holder,games,coreLegs,latest,gates,gateNames,facts,date}){
 if(date!==visibleDate){
   flippedKey=null;visibleDate=date;
   document.body?.classList?.remove("pool-card-open");
 }
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
 for(const g of games)card(holder,g,coreKeys,latest,gates,gateNames,facts,date);
}
document.addEventListener?.("keydown",event=>{
 if(event.key!=="Escape"||!flippedKey)return;
 const card=document.querySelector?.('.pool-flip-card[data-card-key="'+flippedKey+'"]');
 const holder=card?.parentElement;
 if(holder){toggle(holder,flippedKey);card.querySelector?.(".pool-front-turn")?.focus?.();}
});
const api={render};
if(typeof module!=="undefined"&&module.exports)module.exports=api;
root.ElitePool=api;
})(typeof window!=="undefined"?window:globalThis);
