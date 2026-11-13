import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const source=await readFile(new URL('./dashboard.js',import.meta.url),'utf8');
new vm.Script(source);
const elements=new Map();
const $=id=>{if(!elements.has(id))elements.set(id,{textContent:'',innerHTML:'',style:{},value:'all',disabled:false,classList:{toggle(){},add(){}},replaceChildren(){this.innerHTML='';},querySelectorAll(){return [];}});return elements.get(id);};
let now=Date.now();
class Clock extends Date {static now(){return now;}}
const state={executionVersion:0,executionAction:null,executionSource:null,run:null,report:{id:'new-report',data:{config:{}}},filtered:[],curve:[],trades:[{entryUtc:'old',net:111}],loadedRun:'old'};
let aborted=false,cleared=false,timer;
const context=vm.createContext({$,state,Date:Clock,stamp:String,number:String,money:String,esc:String,setColor(){},periodLabel(){return 'period';},notify(){},AbortController,phoneAccess:false,phoneSession:'',
 setTimeout:fn=>{timer=fn;return 1;},clearTimeout:()=>{cleared=true;},
 fetch:(url,{signal})=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>{aborted=true;reject(new Error('aborted'));})),
 stopReplay(){},fillTradeSelect(){},drawChart(){},renderTrades(){}});
vm.runInContext(source.slice(source.indexOf('async function api('),source.indexOf('function notify(')),context);
const hanging=vm.runInContext("api('/api/status')",context);
timer();await assert.rejects(hanging,/aborted/);assert(aborted&&cleared,'API deadline must abort hung requests and release its timer');
vm.runInContext(source.slice(source.indexOf('function executionSummary'),source.indexOf('async function executionPost')),context);
vm.runInContext("renderExecution({active:true,config:null,status:{state:'running',heartbeatUtc:new Date(Date.now()).toISOString(),message:'ok'}})",context);
assert.equal($('bot-pill').textContent,'LIVE');
now+=16000;vm.runInContext('updateBotPill()',context);
assert.equal($('bot-pill').textContent,'DISCONNECTED','Heartbeat expires without another API response');
const requests=[];
context.api=()=>new Promise(resolve=>requests.push(resolve));
vm.runInContext(source.slice(source.indexOf('async function selectRun('),source.indexOf('function drawChart(')),context);
const run=name=>({name,equityNet:222,initial:50000,maxEquityDDPct:1,rr:5,startUtc:'2026-01-01',endUtcExclusive:'2026-05-01',slippageUsdOz:.1});
context.next=run('first');const first=vm.runInContext('selectRun(next)',context);
assert.equal(state.trades.length,0);assert.equal(state.loadedRun,null);assert.equal($('export-button').disabled,true);
context.next=run('second');const second=vm.runInContext('selectRun(next)',context);
requests[0]([{equity:1}]);requests[1]([{net:1}]);await first;
assert.equal(state.loadedRun,null,'A late response from the previous selection stays discarded');
requests[2]([{equity:2}]);requests[3]([{net:2}]);await second;
assert.equal(state.trades[0].net,2);assert.equal($('export-button').disabled,false);assert(state.loadedRun.includes('second'));
console.log('Dashboard checks PASS: syntax, hung API cancellation, independent heartbeat expiry, stale trade clearing, late-response isolation.');

// Stop acknowledgement and an old in-flight refresh must never leave a LIVE badge.
state.reports=[];
vm.runInContext(source.slice(source.indexOf('async function executionPost('),source.indexOf('async function loadExecutionAccounts(')),context);
vm.runInContext(source.slice(source.indexOf('async function stopExecution('),source.indexOf("$('execution-stop').onclick=stopExecution")),context);
vm.runInContext(source.slice(source.indexOf('async function refresh()'),source.indexOf("for(const button of document.querySelectorAll('[data-page]'))button.onclick")),context);
vm.runInContext('var refreshing=false;',context);
const running={active:true,config:{account:{broker:'FxPro',login:'456'}},status:{state:'running',heartbeatUtc:new Date(now).toISOString(),message:'running'}};
const stopping={...running,status:{...running.status,state:'stopping',message:'Stopping'}};
const idle={...running,active:false,status:{...running.status,state:'idle',message:'Stopped'}};
context.initial=running;vm.runInContext('renderExecution(initial)',context);
let resolveOldStatus,resolveIdle;
context.api=path=>{
 if(path==='/api/status')return new Promise(resolve=>{resolveOldStatus=resolve;});
 if(path==='/api/reports')return Promise.resolve([]);
 if(path==='/api/session')return Promise.resolve({csrf:'test'});
 if(path==='/api/execution/stop')return Promise.resolve(stopping);
 if(path==='/api/execution')return new Promise(resolve=>{resolveIdle=resolve;});
 throw new Error(path);
};
const oldRefresh=vm.runInContext('refresh()',context);
const stop=vm.runInContext('stopExecution()',context);
assert.equal($('execution-stop').textContent,'Stopping…');
assert.equal($('bot-pill').textContent,'STOP REQUESTED');
await new Promise(resolve=>setImmediate(resolve));
assert.equal($('bot-pill').textContent,'STOPPING');
assert.equal($('execution-start').disabled,true);
resolveOldStatus({execution:running,jobs:[],dataDays:120,fullReportReady:true});await oldRefresh;
assert.equal(state.execution.status.state,'stopping','Old polling response cannot overwrite Stop acknowledgement');
assert.equal($('bot-pill').textContent,'STOPPING');
resolveIdle(idle);await stop;
assert.equal($('bot-pill').textContent,'IDLE');
assert.equal($('execution-stop').disabled,true);assert.equal($('execution-start').disabled,false);
assert.equal(state.executionAction,null);
console.log('Stop UI checks PASS: immediate feedback, STOPPING instead of LIVE, stale refresh ignored, confirmed IDLE.');
