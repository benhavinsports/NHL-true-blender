/* Node built-in tests: actual saved NHL gate receipts drive the card back.
   No browser library and no manually selected scorers. */
"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const root=path.resolve(__dirname,"../..");
const facts=require("../gate-facts.js");
const raw=fs.readFileSync(path.join(root,"state/site_gates/2026-11-17.json"),"utf8");
const saved=JSON.parse(raw);
const run=JSON.parse(fs.readFileSync(path.join(root,"state/site_runs/2026-11-17.json"),"utf8"));
const card=JSON.parse(fs.readFileSync(path.join(root,"state/site_cards/2026-11-17.json"),"utf8"));

class FakeNode{
 constructor(tag){
   this.tagName=tag;this.childNodes=[];this.dataset={};this.attributes={};
   Object.defineProperty(this,'children',{get:()=>this.childNodes});
   this.listeners={};this.hidden=false;this._className="";this._classes=new Set();
   this.classList={
     add:(name)=>this._classes.add(name),
     contains:(name)=>this._classes.has(name),
     toggle:(name,force)=>{
       const active=force===undefined?!this._classes.has(name):force;
       if(active)this._classes.add(name);else this._classes.delete(name);
       return active;
     }
   };
 }
 set className(value){this._className=value;this._classes=new Set(String(value).split(/\s+/));}
 get className(){return [...this._classes].join(" ");}
 appendChild(x){this.childNodes.push(x);return x;}
 replaceChildren(...x){this.childNodes=x;}
 setAttribute(k,v){this.attributes[k]=String(v);}
 getAttribute(k){return this.attributes[k];}
 querySelector(selector){
   const klass=String(selector).startsWith(".")?String(selector).slice(1):null;
   if(!klass)return null;
   const search=node=>{
     for(const child of node.childNodes){
       if(child.classList?.contains(klass))return child;
       const result=search(child);
       if(result)return result;
     }
     return null;
   };
   return search(this);
 }
 addEventListener(event,cb){this.listeners[event]=cb;}
 scrollIntoView(){}
}
function descendants(node){
 return [node,...(node.childNodes||[]).flatMap(descendants)];
}
function appContext(){
 const elements={
   "core-cards":new FakeNode("div"),
   "pool-list":new FakeNode("div"),
   "core":new FakeNode("section")
 };
 const document={
   createElement:(tag)=>new FakeNode(tag),
   getElementById:(id)=>elements[id]||null,
   querySelectorAll:(selector)=>selector==="#core-cards .core-card"?
      elements["core-cards"].childNodes.filter(n=>n.classList.contains("core-card")):[]
 };
 const sandbox={document,BlenderGateFacts:facts,Date,Intl,URL,Set,Map,Promise,console};
 vm.createContext(sandbox);
 vm.runInContext(fs.readFileSync(path.join(root,"site/pool-deck.js"),"utf8"),sandbox);
 const script=fs.readFileSync(path.join(root,"site/app.js"),"utf8");
 assert.ok(script.includes("boot().catch("));
 // The test invokes the same app functions without starting network polling.
 vm.runInContext(script.split("boot().catch(")[0],sandbox);
 sandbox.sample={gateData:saved,legs:JSON.parse(card.legsJson),run};
 vm.runInContext(`
   state.selectedDate="2026-11-17";
   state.archive=[{date:"2026-11-17",cardId:sample.gateData.cardId,
     current_legs:sample.legs,verified:true,revision:2}];
   state.latest={date:"2026-11-17",gameSurvivorPool:sample.run.gameSurvivorPool};
   state.gateData=sample.gateData;
   state.selectedLeg=String(sample.legs[0].gameId)+":"+String(sample.legs[0].playerId);
 `,sandbox);
 return {sandbox,elements,vm};
}

test("all 20 original gates have source-driven readable reasons on real saved card backs",()=>{
 assert.equal(saved.legs.length,3);
 const gates=[...Array(11)].map((_,i)=>"G"+i).concat("G10.5",...[...Array(8)].map((_,i)=>"G"+(i+11)));
 for(const leg of saved.legs){
   assert.deepEqual(leg.gateDetails.map(g=>g.gate),gates);
   for(const rec of leg.gateDetails){
     const why=facts.explanation(rec);
     assert.ok(why.length>=50,rec.gate+" only generated "+why);
     assert.notEqual(why,"PASS");
     assert.ok(!why.includes("undefined"),rec.gate+" has undefined evidence");
   }
 }
});

test("no matching pre-puck evidence cannot be presented as PASS",()=>{
 assert.match(facts.explanation({gate:"G10.5",status:"PASS",
   prePuckRecord:false,evidence:{}}),/unavailable/i);
 assert.match(facts.explanation({gate:"G17",status:"NOT_EXECUTED",
   prePuckRecord:true,evidence:{}}),/did not pass/i);
 assert.equal(facts.sourceCount({sourceIds:[
   "https://api-web.nhle.com/v1","https://api-web.nhle.com/v1",
   "not-a-source"]}),1);
});

test("tapping Core card toggles physical back with all 20 reasons in place",()=>{
 const {sandbox,elements}=appContext();
 vm.runInContext("renderCards()",sandbox);
 const cardNode=elements["core-cards"].childNodes[0];
 assert.equal(cardNode.tagName,"div");
 assert.equal(cardNode.getAttribute("role"),"button");
 assert.equal(descendants(cardNode).filter(n=>n.classList.contains("card-back")).length,1);
 assert.equal(descendants(cardNode).filter(n=>n.classList.contains("flip-gate-row")).length,20);
 const allSources=descendants(cardNode).filter(n=>n.tagName==="a");
 assert.ok(allSources.length>=20,"source links should live on the back of the actual card");
 assert.ok(allSources.every(n=>n.href.startsWith("https://")));
 const content=descendants(cardNode).filter(n=>n.classList.contains("flip-function-line"));
 assert.ok(content.length>=16,"nested original functions are inspectable on the card back");
 assert.equal(cardNode.getAttribute("aria-expanded"),"false");
 cardNode.listeners.click();
 assert.equal(cardNode.classList.contains("is-flipped"),true);
 assert.equal(cardNode.getAttribute("aria-expanded"),"true");
 cardNode.listeners.click();
 assert.equal(cardNode.classList.contains("is-flipped"),false);
 assert.equal(cardNode.getAttribute("aria-expanded"),"false");
});

test("every scheduled game is a concise two-sided survivor card, not a public audit",()=>{
 const {sandbox,elements}=appContext();
 vm.runInContext("renderPool()",sandbox);
 const board=elements["pool-list"];
 const cards=board.childNodes.filter(n=>n.classList.contains("pool-flip-card"));
 const receipts=run.gameSurvivorPool||[];
 assert.equal(cards.length,11);
 assert.equal(cards.length,receipts.length);
 const count=receipts.filter(g=>g.survivor&&g.status==="SURVIVOR").length;
 const stats=descendants(board.childNodes[0]).map(n=>n.textContent||"").join(" ");
 assert.ok(stats.includes(count+" / "+receipts.length));
 for(let i=0;i<receipts.length;i++){
   const g=receipts[i],card=cards[i];
   assert.equal(descendants(card).filter(n=>n.classList.contains("pool-face")).length,2);
   const front=descendants(card).find(n=>n.classList.contains("pool-front"));
   const back=descendants(card).find(n=>n.classList.contains("pool-back"));
   const frontText=descendants(front).map(n=>n.textContent||"").join(" ");
   const backText=descendants(back).map(n=>n.textContent||"").join(" ");
   assert.ok(frontText.includes(g.matchup.replace("@"," @ ")));
   assert.ok(!frontText.includes("Opposing goalie NHL ID"));
   assert.ok(!frontText.includes("G16 cross-game"));
   if(g.survivor){
     assert.ok(frontText.includes(g.survivor.player));
     assert.ok(frontText.includes(g.survivor.routeLabel));
     assert.ok(backText.includes("G16"));
     assert.ok(backText.includes(String(g.survivor.goalieId)));
   }else{
     assert.ok(!frontText.includes("GAME SURVIVOR"));
   }
 }
 const first=cards[0],button=descendants(first).find(n=>n.classList.contains("pool-front-turn"));
 assert.equal(button.tagName,"button");
 button.listeners.click();
 assert.equal(first.classList.contains("is-flipped"),true);
 const backbutton=descendants(first).find(n=>n.classList.contains("pool-back-turn"));
 backbutton.listeners.click();
 assert.equal(first.classList.contains("is-flipped"),false);
});

test("additional full gate evidence appears only when matching original receipts exist",()=>{
 const {sandbox,elements}=appContext();
 // The current run can legitimately have zero survivors after a newer
 // source check. Use a saved original Core receipt as a UI-only fixture.
 const first=run.gameSurvivorPool.find(g=>g.survivor)||{
   gameId:saved.legs[0].gameId,matchup:saved.legs[0].matchup,
   status:"SURVIVOR",
   survivor:{player:saved.legs[0].player,playerId:saved.legs[0].playerId,
     routeLabel:saved.legs[0].originalLockedPath,ownRouteZone:"Low Slot",
     ownedGoals:1,ownShotsOnGoal:4}
 };
 assert.ok(first);
 const proof=saved.legs[0].gateDetails.map(x=>({
   ...x, originalFunctions:(x.evidence?.originalFunctionEvidence||[])
     .map(y=>({step:y.step,status:y.disposition}))
 }));
 sandbox.sample.proof=proof;
 sandbox.sample.first=first;
 vm.runInContext(
   'state.latest.gameSurvivorPool=[sample.first];' +
   'state.latest.gameSurvivorGateReceipts={' +
   '  [String(sample.first.gameId)+":"+' +
   'String(sample.first.survivor.playerId)]:sample.proof};',
   sandbox);
 vm.runInContext("renderPool()",sandbox);
 const firstCard=elements["pool-list"].childNodes
   .find(n=>n.classList.contains("pool-flip-card")&&
      n.dataset.cardKey===String(first.gameId));
 assert.equal(descendants(firstCard).filter(n=>n.classList.contains("pool-gate-proof")).length,20);
 assert.ok(descendants(firstCard).some(n=>n.tagName==="a"&&
   String(n.href||"").startsWith("https://")));
});
test("public HTML never renders the duplicate behind-the-pick audit",()=>{
 const html=fs.readFileSync(path.join(root,"site/index.html"),"utf8");
 assert.ok(!html.includes('id="evidence"'));
 assert.ok(!html.includes('id="leg-detail"'));
 assert.ok(!html.includes("Behind the pick"));
 assert.ok(!html.includes('href="#evidence"'));
 assert.ok(html.includes('id="core-cards"'));
 assert.ok(html.includes('id="pool-list"'));
 assert.ok(html.includes('./pool-deck.js'));
 assert.ok(!html.includes('id="system"'));
 assert.ok(!html.includes('id="slate"'));
 assert.ok(!html.includes('id="master-gate-deck"'));

});


test("scouting visual identity has no poker suit, cartoon rink or editable dashboard UI",()=>{
 const html=fs.readFileSync(path.join(root,"site/index.html"),"utf8");
 const js=fs.readFileSync(path.join(root,"site/app.js"),"utf8");
 const pool=fs.readFileSync(path.join(root,"site/pool-deck.js"),"utf8");
 const css=fs.readFileSync(path.join(root,"site/styles.css"),"utf8");
 assert.ok(html.includes("NHL SCOUTING INTELLIGENCE"));
 assert.ok(html.includes("THE AUTHORITATIVE SELECTION"));
 assert.ok(!html.includes("♠"));
 assert.ok(!html.includes("hand-ornament"));
 assert.ok(!js.includes('"rink-center"'));
 assert.ok(!js.includes('"face-corner"'));
 assert.ok(js.includes('"collector-photo"'));
 assert.ok(!js.includes('"card-profile-number"'));
 assert.ok(!pool.includes('"pool-card-suit"'));
 assert.ok(pool.includes("pool-card-open"));
 assert.ok(css.includes("SCOUTING INTELLIGENCE"));
 assert.ok(css.includes("body.pool-card-open"));
 assert.ok(html.includes('id="pool-list"'));
 assert.ok(html.includes('id="core-cards"'));
 assert.ok(!html.includes('id="system"'));
});


test("Core card fronts are real photo-led collector designs with saved NHL IDs",()=>{
 const {sandbox,elements}=appContext();
 vm.runInContext("renderCards()",sandbox);
 const cards=elements["core-cards"].childNodes;
 assert.equal(cards.length,3);
 for(let i=0;i<cards.length;i++){
   const leg=JSON.parse(card.legsJson)[i];
   const front=descendants(cards[i]).find(n=>n.classList.contains("card-front"));
   const back=descendants(cards[i]).find(n=>n.classList.contains("card-back"));
   const photo=descendants(front).find(n=>n.classList.contains("collector-photo"));
   assert.ok(photo,"Missing actual NHL photo element for "+leg.player);
   assert.ok(photo.src.includes("/mugs/actionshots/1296x729/"+leg.playerId+".jpg"));
   assert.ok(photo.alt.includes(leg.player));
   assert.ok(descendants(front).some(n=>n.classList.contains("collector-foil-rings")));
   assert.ok(descendants(front).some(n=>n.classList.contains("collector-path-row")));
   const text=descendants(front).map(n=>n.textContent||"").join(" ");
   assert.ok(text.includes(leg.player.split(/\s+/).at(-1).toUpperCase()));
   assert.ok(text.includes(leg.path));
   assert.ok(text.includes(leg.directRoute.split("/").at(-1).trim()));
   assert.ok(!text.includes("SELECTION 01"));
   assert.ok(!text.includes("TRUE BLENDER / NHL 01"));
   assert.ok(descendants(back).filter(n=>n.classList.contains("flip-gate-row")).length===20);
 }
 const first=descendants(cards[0]).find(n=>n.classList.contains("collector-photo"));
 assert.equal(typeof first.listeners.error,"function");
 first.listeners.error();
 assert.ok(first.src.includes("/mugs/nhl/20262027/"),
     "If official NHL action still is unavailable, official headshot should be attempted");
});

test("Mobile collector cards use a two-up grid with centered third, never a clipped carousel",()=>{
 const css=fs.readFileSync(path.join(root,"site/styles.css"),"utf8");
 const block=css.slice(css.lastIndexOf("CORE FRONT · PREMIUM HOCKEY COLLECTOR SERIES"));
 assert.ok(block.includes("grid-template-columns:repeat(2,minmax(0,1fr))"));
 assert.ok(block.includes(".core-grid>.core-card:nth-child(3)"));
 assert.ok(block.includes("overflow:visible"));
 assert.ok(block.includes("collector-photo"));
 assert.ok(block.includes("collector-foil-rings"));
});


test("CSS keeps the photograph collector face full-height within rotating card",()=>{
 const css=fs.readFileSync(path.join(root,"site/styles.css"),"utf8");
 const last=css.slice(css.lastIndexOf("photo collector front is an entire flip plane"));
 assert.ok(last.includes(".core-card .card-face.card-front"));
 assert.match(last,/position\s*:\s*absolute/);
 assert.match(last,/height\s*:\s*100%/);
 // If the entire front is position:relative, every absolutely positioned
 // child renders above a 0px-height box and the real cards look empty.
});
