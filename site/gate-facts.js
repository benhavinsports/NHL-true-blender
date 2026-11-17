/* Source-grounded, human-readable explanations for the original G0–G18.
   This module NEVER changes a gate verdict or chooses a scorer. */
(function(root){
"use strict";
function text(v){return v===undefined||v===null||v===""?"not reported":String(v);}
function count(v){return Array.isArray(v)?v.length:0;}
function areas(v){return v&&typeof v==="object"&&!Array.isArray(v)?Object.keys(v).join(", "):"";}
function small(v){return typeof v==="number"&&Number.isFinite(v)?v:null;}
function sourceCount(record){
 return new Set((record?.sourceIds||[]).filter(s=>typeof s==="string"&&s.startsWith("https://"))).size;
}
function explanation(record){
 if(!record||!record.evidence||record.prePuckRecord!==true)
   return "A matching original pre-puck gate receipt is unavailable; no passing decision is assumed.";
 if(record.status!=="PASS")
   return "Gate did not pass in this saved source review. Inspect its recorded evidence and unresolved conditions.";
 const e=record.evidence;
 switch(record.gate){
 case "G0":
   return text(e.selectedAttacker||e.attacker)+" attacks "+text(e.selectedDefender)+
     " against goalie ID "+text(e.targetGoalie)+" ("+text(e.branchStatus)+
     "). Measured vulnerable shot origins: "+(areas(e.weakZones)||"not reported")+".";
 case "G1": {
   const c=e.venueRestTravel||{};
   return "Venue and both teams' rest reviewed"+
     (c.awayRestDays!=null&&c.homeRestDays!=null?
       " (away "+c.awayRestDays+" day(s), home "+c.homeRestDays+" day(s))":"")+
     ". Travel mileage is not invented when unavailable.";
 }
 case "G2":
   return "Official roster review: "+text(e.availability)+" · "+text(e.position)+
     " · "+text(e.fullPoolSize)+" eligible skaters reviewed. Dressed status is not inferred from roster listing.";
 case "G3": {
   const weak=e.goalieWeakZones||{}, sample=e.goalieSample||{};
   const zone=Object.keys(weak)[0],obs=weak[zone]||{};
   return "Measured opposing-goalie vulnerable origin: "+(areas(weak)||"not reported")+
     (small(obs.goalsAgainst)!==null?" ("+obs.goalsAgainst+" goals allowed on "+text(obs.shotsAgainst)+" on-net shots)":"")+
     (small(sample.allZoneObservations)!==null?"; "+sample.allZoneObservations+" total observed area events.":".")+
     " Rink origin is not goalie anatomy.";
 }
 case "G4": {
   const x=e.ownRelease||{};
   return "Own measured scoring origin: "+text(x.zone)+" · "+
     text(x.attempts)+" own on-net shots and "+text(x.ownedGoals)+
     " credited goals in that area ("+text(e.archetype)+").";
 }
 case "G5":
   return "Shooter's own "+text(e.shooterZone)+" scoring origin intersects goalie weakness in "+
     (areas(e.weakZones)||"an unreported area")+
     ". Strong goalie origins "+(areas(e.goalieStrengthZones)||"not reported")+" are separately reviewed.";
 case "G6": {
   const d=e.deployment||{};
   return text(d.status)+" deployment: even strength "+text(d.EV||d.line)+
     ", power-play unit "+text(d.powerPlayUnit||d.PP)+
     ". The source status remains "+text(d.status)+"; projected never means confirmed.";
 }
 case "G7":
   return text(e.distinctGoalDates)+" distinct credited goal date(s) and "+
     text(e.positiveDatedShotAppearances)+" actual appearances with own shots; "+
     "missed games and same-date multi-goal inflation are excluded.";
 case "G8":
   return "Game and market context reviewed neutrally. Missing odds or markets do not rank, select, or disqualify a scorer.";
 case "G9": {
   const z=e.zoneConcessionEvidence||{};
   return "Opponent defensive coverage at "+text(e.shooterZone)+": "+
     text(z.attemptsAgainst)+" historical shot attempts over "+text(z.gameCount)+
     " games ("+text(z.attemptsPerGame)+"/game, peer median "+
     text(z.peerMedianAttemptsPerGame)+"). Green attacking origins: "+
     (Array.isArray(e.greenTarget)&&e.greenTarget.length?e.greenTarget.join(", "):"not reported")+
     ". Based on historical rink shot origins, not anatomical goalie holes.";
 }
 case "G10":
   return "Official prior-game goal credit verified via "+
     text(e.historicalDirectGoalRecipientVerificationMethod).replace(/_/g," ").toLowerCase()+
     ". Historical finishing does not establish who scores tonight.";
 case "G10.5":{
   const rows=e.comparisonRows||[],defeated=rows.filter(x=>x.status==="DEFEATED").length;
   return "All "+rows.length+" active teammate route(s) compared with independent evidence; "+
     defeated+" directly defeated, "+
     rows.filter(x=>x.status==="DIFFERENT_TARGET_LANE").length+" on different target lanes. "+
     "No unsupported PRIMARY-to-TRANSFER switch.";
 }
 case "G11":{
   const p=e.shotContinuation||{};
   return "Individual on-net shot pressure observed in "+
     text(p.positiveDatedShotAppearances||p.positiveShotAppearances)+
     " actual appearances; recurring attempts confirmed, not a one-game spike.";
 }
 case "G12":
   return "Official credited goal records reconciled to dated game evidence and the player's own historical goal ownership.";
 case "G13":
   return "Qualitative name / jersey / slate-date review: "+
     text(e.name)+" · #"+text(e.jersey)+" · "+text(e.date)+
     ". No invented numerology score or selection weight.";
 case "G14":
   return e.whoAnomalyPhysicallySupported===true?
     "Unusual independent scoring route was source-supported and reviewed with the goalie target.":
     "Unusual WHO route checked; no separate supported anomaly was asserted or forced.";
 case "G15":
   return "Independent historical finishing cross-check: "+
     text(e.officialOwnedGoalsInMatchedOrigin)+" credited goal(s) from the selected shot origin"+
     (small(e.officialDatedSeasonGoals)!==null?" versus "+e.officialDatedSeasonGoals+" dated season goal(s)":"")+
     ". This is corroboration, not a guarantee of tonight's finisher.";
 case "G16":
   return "Compared the player's own scoring route against "+
     text(e.everyOtherActiveTeammate)+" active teammates, including depth and defenders. "+
     "Recorded challenger evidence was checked before Core assembly.";
 case "G17":
   return "Independent opponent-goalie strength, lineup disagreement, and same-route rival contradictions were reviewed; "+
     (e.sourceDerivedReviewResolved===true?"source review resolved.":"no resolved finding is shown.") ;
 case "G18": {
   const p=e.pathClassificationEvidence||{};
   return "Full prior-gate survivor assembled onto the Core only after G16. "+
     "Recorded scoring route "+text(p.path)+
     (p.scoringLane?" · "+p.scoringLane:"")+
     (p.rationale?" — "+p.rationale:"")+".";
 }
 default:
   return "Original source review recorded. Open the full gate receipt for its dated evidence.";
 }
}
const api={explanation,sourceCount};
if(typeof module!=="undefined"&&module.exports)module.exports=api;
root.BlenderGateFacts=api;
})(typeof window!=="undefined"?window:globalThis);
