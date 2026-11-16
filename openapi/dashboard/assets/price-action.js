'use strict';
// Research-only, closed-bar structure. A pivot is never known before its two right bars close.
window.paStructure=(input,cursor=input.length-1)=>{
 const bars=input.slice(0,cursor+1);let pivots=[],breaks=[],segment=0,direction=null,high=null,low=null;
 for(let i=0;i<bars.length;i++){
  const b=bars[i],previous=bars[i-1];
  if(previous&&(b.startUtc.slice(0,10)!==previous.endUtc.slice(0,10)||Date.parse(b.startUtc)-Date.parse(previous.endUtc)>60000)){
   pivots=[];breaks=[];segment=i;direction=null;high=low=null;
  }
  if(i-segment>=4){
   const p=bars[i-2],neighbors=[bars[i-4],bars[i-3],bars[i-1],b];
   for(const type of ['high','low']){
    const price=p[type],isHigh=type==='high';
    if(!neighbors.every(n=>isHigh?price>n.high:price<n.low))continue;
    const old=pivots.filter(x=>x.type===type).at(-1);
    const label=!old?(isHigh?'H':'L'):price===old.price?(isHigh?'EH':'EL'):isHigh?(price>old.price?'HH':'LH'):(price>old.price?'HL':'LL');
    const pivot={type,price,label,index:p.time,knownIndex:b.time,knownUtc:b.endUtc};pivots.push(pivot);
    if(isHigh)high={...pivot,broken:false};else low={...pivot,broken:false};
   }
  }
  for(const [pivot,next] of [[high,'up'],[low,'down']]){
   if(!pivot||pivot.broken||!(next==='up'?b.close>pivot.price:b.close<pivot.price))continue;
   const kind=direction&&direction!==next?'Character shift':'BOS';
   breaks.push({time:b.time,direction:next,kind,price:pivot.price,utc:b.endUtc});pivot.broken=true;direction=next;
  }
 }
 const highs=pivots.filter(p=>p.type==='high').slice(-2),lows=pivots.filter(p=>p.type==='low').slice(-2);
 let regime='Unknown',reason='Need two confirmed highs and two confirmed lows.';
 if(highs.length===2&&lows.length===2){
  const h=Math.sign(highs[1].price-highs[0].price),l=Math.sign(lows[1].price-lows[0].price);
  regime=h===1&&l===1?'Uptrend':h===-1&&l===-1?'Downtrend':h===0||l===0?'Transition':'Range / mixed';
  reason=`Highs ${highs[0].price.toFixed(2)} → ${highs[1].price.toFixed(2)}; lows ${lows[0].price.toFixed(2)} → ${lows[1].price.toFixed(2)}.`;
 }
 if((regime==='Uptrend'&&low?.broken)||(regime==='Downtrend'&&high?.broken)){regime='Transition';reason+=' Last supporting swing was broken by a close.';}
 return {pivots,breaks,regime,reason,segmentStart:bars[segment]?.time??0};
};
window.paSetup=(zone,entry,range,structure)=>{
 const long=zone.long,buffer=range*.1,stop=long?Math.min(zone.low-buffer,entry-3):Math.max(zone.high+buffer,entry+3);
 const targets=structure.pivots.filter(p=>p.type===(long?'high':'low')&&(long?p.price>entry:p.price<entry)).map(p=>p.price);
 const target=targets.length?(long?Math.min(...targets):Math.max(...targets)):null;
 const rr=target===null?null:Math.abs(target-entry)/Math.abs(entry-stop),aligned=structure.regime===(long?'Uptrend':'Downtrend');
 const eligible=aligned&&rr!==null&&rr>=3-1e-9;
 const reason=target===null?'No confirmed swing target ahead.':!aligned?'Regime does not align with setup.':rr<3-1e-9?'Nearest swing target gives less than3R.':'Aligned structure and geometric RR ≥3.';
 return {side:long?'BUY':'SELL',entry,stop,target,rr,eligible,reason};
};
window.paToolkitFrame=(snapshot,bars)=>{
 const structure=window.paStructure(bars),cutoff=Date.parse(bars.at(-1)?.endUtc||0);
 const confirmed=snapshot.events.filter(e=>e.kind==='confirmed'&&Date.parse(e.utc)<=cutoff&&e.barIndex>=structure.segmentStart&&e.barIndex<=bars.length).at(-1);
 let setup=null;
 if(confirmed){const index=confirmed.barIndex-1,b=bars[index];if(b)setup={...window.paSetup(confirmed.zone,b.close,snapshot.rangeUsdOz,window.paStructure(bars,index)),utc:confirmed.utc,barIndex:confirmed.barIndex};}
 const markers=structure.pivots.slice(-40).map(p=>({time:p.index,position:p.type==='high'?'aboveBar':'belowBar',shape:'circle',color:'#a6b7cc',text:p.label}));
 markers.push(...structure.breaks.slice(-15).map(e=>({time:e.time,position:e.direction==='up'?'aboveBar':'belowBar',shape:e.direction==='up'?'arrowUp':'arrowDown',color:'#d4b477',text:e.kind==='BOS'?'BOS':'Shift'})));
 return {structure,setup,markers};
};
