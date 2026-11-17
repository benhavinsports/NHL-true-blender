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

test("full slate shows all 11 separate source decisions without invented survivors",()=>{
 const {sandbox,elements}=appContext();
 vm.runInContext("renderPool()",sandbox);
 const board=elements["pool-list"];
 const panels=board.childNodes.filter(n=>n.classList.contains("survivor-match"));
 assert.equal(panels.length,11);
 const receipts=run.gameSurvivorPool||[];
 assert.equal(panels.length,receipts.length);
 const verified=receipts.filter(g=>g.survivor&&g.status==="SURVIVOR").length;
 assert.ok(verified<=receipts.length);
 assert.equal(board.childNodes[0].childNodes[0].textContent,verified+" / "+receipts.length+" verified game survivors");
 // A fully qualified slate can correctly have ZERO unresolved games.
 // The old unconditional missing-evidence assertion made Pages deployment
 // fail precisely when all eleven matchups produced source-backed survivors.
 for(const [i,receipt] of receipts.entries()){
   const rendered=descendants(panels[i]).map(n=>n.textContent||"").join(" ");
   if(receipt.status==="SURVIVOR" && receipt.survivor){
     assert.ok(rendered.includes(receipt.survivor.player),
       "Published game survivor must match saved independent engine identity");
     assert.ok(["PRIMARY","TRANSFER","WHO"].includes(receipt.survivor.routeLabel),
       "Source-certified game survivor must have an evidence-based path");
     assert.ok(!rendered.includes("No source-qualified survivor yet"),
       "Certified game survivor cannot still show an evidence blocker");
   }else{
     assert.match(rendered,/No source-qualified survivor yet|selection frozen|unseparated/i);
   }
   assert.ok(!/faker|placeholder pick/i.test(rendered));
 }
});

test("public HTML never renders the duplicate behind-the-pick audit",()=>{
 const html=fs.readFileSync(path.join(root,"site/index.html"),"utf8");
 assert.ok(!html.includes('id="evidence"'));
 assert.ok(!html.includes('id="leg-detail"'));
 assert.ok(!html.includes("Behind the pick"));
 assert.ok(!html.includes('href="#evidence"'));
 assert.ok(html.includes('id="core-cards"'));
});
