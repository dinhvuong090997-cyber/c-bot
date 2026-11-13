'use strict';
const $ = id => document.getElementById(id);
const phoneAccess=!['localhost','127.0.0.1'].includes(location.hostname);
let phoneSession=document.querySelector('meta[name="aurum-phone-session"]')?.content||'';
if(phoneAccess) {
  try {
    if(phoneSession)sessionStorage.setItem('aurum-phone-session',phoneSession);
    else phoneSession=sessionStorage.getItem('aurum-phone-session')||'';
  } catch (_) { /* The paired page still works with an in-memory session. */ }
  if(phoneSession&&location.pathname==='/pair')history.replaceState(null,'','/#backtests');
}

const state = {reports:[], report:null, run:null, curve:[], trades:[], mode:'equity', page:'backtests', tradePage:0, csrf:'', status:null, preset:null, pendingJob:null, userReport:false, execution:null, executionSource:null, executionVersion:0, executionAction:null, readOnly:false, market:null, baseBars:new Map(), historyVersion:'', livePeriod:5, btPeriod:5, selectedTrade:-1, priceBars:[], priceTicket:0, priceKey:'', replayTimer:null};
const money = (n, digits=2) => n==null?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',minimumFractionDigits:digits,maximumFractionDigits:digits}).format(n ?? 0);
const number = (n, digits=1) => n==null?'—':new Intl.NumberFormat('en-US',{maximumFractionDigits:digits}).format(n ?? 0);
const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stamp = v => new Date(v).toLocaleString('en-GB',{timeZone:'UTC',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});
const periodKey = r => `${r.startUtc}|${r.endUtcExclusive}`;
const periodLabel = (start,end) => `${new Date(start).toLocaleDateString('en-US',{timeZone:'UTC',month:'short',day:'numeric'})} – ${new Date(new Date(end)-86400000).toLocaleDateString('en-US',{timeZone:'UTC',month:'short',day:'numeric',year:'numeric'})}`;
const setColor = (el,n) => {el.classList.toggle('negative',n<0);el.classList.toggle('positive',n>0);};
async function api(path, options={}) {
  const headers={...(options.headers||{})};
  if(phoneAccess&&phoneSession)headers.Authorization='Bearer '+phoneSession;
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),options.method==='POST'||path.startsWith('/api/backtest-bars')?100000:15000);
  try {
    const response=await fetch(path,{cache:'no-store',...options,headers,signal:controller.signal});
    const data=await response.json();
    if(response.status===401&&phoneAccess){try{sessionStorage.removeItem('aurum-phone-session');}catch(_){}location.replace('/pair');}
    if(!response.ok)throw new Error(data.error||'The local service is unavailable.');
    return data;
  } finally {clearTimeout(timer);}
}
function notify(text,error=false) {const el=$('notice');el.textContent=text;el.hidden=false;el.classList.toggle('error',error);}
function navigate(page) {
  if(!['overview','backtests','trades','settings'].includes(page)) page='backtests';
  state.page=page;location.hash=page;
  for(const el of document.querySelectorAll('.page'))el.hidden=el.id!==page+'-page';
  for(const el of document.querySelectorAll('[data-page]'))el.classList.toggle('active',el.dataset.page===page);
  const title=page==='overview'?'Execution Terminal':page[0].toUpperCase()+page.slice(1);
  $('breadcrumb').textContent=$('page-title').textContent=title;
  $('page-description').textContent={overview:'Real-time execution and monitoring for your XAUUSD strategy.',backtests:'Test the rules. Understand the risk.',trades:'Recorded fills from the selected historical backtest.',settings:'Connection and research preferences.'}[page];
  $('export-button').hidden=page==='settings'||page==='overview';
  $('new-test-button').hidden=page==='settings'||page==='overview';
  $('progress-banner').hidden=page!=='backtests'||!state.status?.jobs?.some(j=>j.state==='running');
 if(page==='trades')renderTrades();
 if(page==='overview'&&liveChart)requestAnimationFrame(()=>renderLiveChart());
 if(page==='backtests'&&backtestChart)requestAnimationFrame(()=>drawChart());
}
function fillSelect(el,values,selected) {
  el.replaceChildren(...values.map(([value,label])=>{const option=document.createElement('option');option.value=value;option.textContent=label;return option;}));
  if(values.some(v=>String(v[0])===String(selected)))el.value=selected;
}
function fullRange(report) {
 const runs=report.data.results;return {start:runs.map(r=>r.startUtc).sort()[0],end:runs.map(r=>r.endUtcExclusive).sort().at(-1)};
}
function chooseReport(id) {
  state.report=state.reports.find(r=>r.id===id)||state.reports.find(r=>r.id==='fxpro-20260101-20260501')||state.reports[0]||null;
  const empty=!state.report;$('empty-state').hidden=!empty;$('result-content').hidden=empty;
  if(empty){state.run=null;state.loadedRun=null;state.trades=[];state.curve=[];$('export-button').disabled=true;renderTrades();return;}
  $('report-select').value=state.report.id;
  const runs=state.report.data.results,full=fullRange(state.report),keys=[...new Set(runs.map(periodKey))];
  keys.sort((a,b)=>a===`${full.start}|${full.end}`?-1:b===`${full.start}|${full.end}`?1:a.localeCompare(b));
  fillSelect($('period-select'),keys.map(k=>{const [a,b]=k.split('|');return [k,`${a===full.start&&b===full.end?'Full period':'Monthly · reset'} · ${periodLabel(a,b)}`];}));
  chooseFilters();
}
function chooseFilters() {
 if(!state.report)return;
 const period=$('period-select').value;
 let rows=state.report.data.results.filter(r=>periodKey(r)===period && r.swapEnabled);
 if(!rows.length)rows=state.report.data.results.filter(r=>periodKey(r)===period);
 const capitals=[...new Set(rows.map(r=>r.initial))].sort((a,b)=>a-b);
 fillSelect($('capital-select'),capitals.map(n=>[n,money(n,0)]),$('capital-select').value);
 const slips=[...new Set(rows.map(r=>r.slippageUsdOz))].sort((a,b)=>a-b);
 fillSelect($('cost-select'),slips.map(n=>[n,n===0?'Quote fills':`+$${n.toFixed(2)} / oz slip`]),$('cost-select').value);
 rows=rows.filter(r=>r.initial===Number($('capital-select').value)&&r.slippageUsdOz===Number($('cost-select').value));
 state.filtered=rows;
 const oldRR=state.run?.rr;selectRun(rows.find(r=>r.rr===oldRR)||rows[0]);
}
async function selectRun(run) {
 if(!run)return;
 state.run=run;state.tradePage=0;state.curve=[];state.trades=[];state.loadedRun=null;state.priceTicket++;state.priceKey='';stopReplay();$('export-button').disabled=true;$('chart-value').textContent=$('chart-date').textContent='Loading…';$('backtest-chart-message').hidden=false;$('backtest-chart-message').textContent='Loading recorded backtest…';renderTrades();
 $('metric-pnl').textContent=money(run.equityNet);setColor($('metric-pnl'),run.equityNet);
 $('metric-return').textContent=`${run.equityNet>=0?'+':''}${number(100*run.equityNet/run.initial,2)}% on ${money(run.initial,0)}`;
 $('metric-dd').textContent=`${number(run.maxEquityDDPct,2)}%`;$('metric-dd').classList.toggle('negative',run.maxEquityDDPct>0);
 $('metric-halt').textContent=run.halted?`Entry halt · ${stamp(run.haltUtc)}`:`${number(run.maxDrawdownPercent??5)}% closed-balance halt`;
 $('metric-costs').textContent=run.swapEnabled?'After commission & swap':'Swap excluded · sensitivity run';
 $('metric-pf').textContent=run.profitFactor==null?'—':number(run.profitFactor,2);
 $('metric-trades').textContent=number(run.trades,0);$('metric-win').textContent=`${number(run.winRate,1)}% win rate · ${run.openPositions} open`;
 const cfg=state.report.data.config||{},asia=cfg.Asia??cfg.asia??true,ny=cfg.NewYork??cfg.newYork??true;
 $('strategy-title').textContent=asia&&ny?'Asia + New York':asia?'Asia momentum':'New York momentum';
 $('strategy-sessions').innerHTML=(asia?'<span>Asia · 00–08 UTC</span>':'')+(ny?'<span>NY · 08–17 local</span>':'');
 $('run-assessment').textContent=run.halted?`Risk limit reached. New entries stopped on ${stamp(run.haltUtc)} UTC.`:run.equityNet<0?'Negative return for this period. This run remains research only.':'Research result. Review independent periods and execution assumptions before validation.';
 $('run-assessment').classList.toggle('risk-reached',run.halted);
 $('strategy-rr').textContent=`1 : ${run.rr}`;$('strategy-risk').textContent=`${run.riskPercent??state.report.data.config?.RiskPercent??state.report.data.config?.riskPercent??0.25}%`;
 $('strategy-stop').textContent=`½ range · min $${state.report.data.config?.MinimumStop??state.report.data.config?.minimumStop??2}`;
 $('curve-subtitle').textContent=periodLabel(run.startUtc,run.endUtcExclusive)+' · '+money(run.initial,0);
 $('curve-legend').textContent=`RR 1:${run.rr} · ${run.slippageUsdOz>0?'slippage scenario':'quote fills'}`;
 $('trades-subtitle').textContent=`${periodLabel(run.startUtc,run.endUtcExclusive)} · RR 1:${run.rr} · ${money(run.initial,0)}`;
 $('run-count').textContent=`${state.filtered.length} runs`;
 $('comparison-body').innerHTML=state.filtered.map((r,index)=>`<tr data-index="${index}" tabindex="0" aria-selected="${r.name===run.name}" class="${r.name===run.name?'selected':''}"><td><span class="config-cell"><i class="radio-dot"></i>RR 1:${esc(r.rr)}</span></td><td class="${r.equityNet<0?'negative':'positive'}">${money(r.equityNet)}</td><td>${number(100*r.equityNet/r.initial,2)}%</td><td>${number(r.maxEquityDDPct,2)}%</td><td>${r.trades}</td><td>${number(r.winRate)}%</td><td>${r.profitFactor==null?'—':number(r.profitFactor,2)}</td><td><span class="table-status ${r.halted?'':'neutral'}">${r.halted?'Halted':'Research'}</span></td></tr>`).join('');
 for(const row of $('comparison-body').querySelectorAll('tr')) {
  const select=()=>selectRun(state.filtered[Number(row.dataset.index)]);row.onclick=select;row.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();select();}};
 }
 const reportId=state.report.id;
 const query=`?report=${encodeURIComponent(reportId)}&run=${encodeURIComponent(run.name)}`;
 try {
  const [curve,trades]=await Promise.all([api('/api/curve'+query),api('/api/trades'+query)]);
  if(state.run?.name!==run.name||state.report?.id!==reportId)return;
  state.curve=curve;state.trades=trades;state.selectedTrade=trades.length-1;state.loadedRun=query;$('export-button').disabled=false;fillTradeSelect();drawChart();renderTrades();
 }catch(e){notify(e.message,true);}
}
let liveChart,backtestChart;
function drawChart() {
 if(!backtestChart||!state.run||!state.loadedRun)return;
 const price=state.mode==='price';$('price-controls').hidden=!price;$('replay-controls').hidden=true;
 if(price){loadTradePrice();return;}
 stopReplay();$('backtest-chart-message').hidden=true;
 const run=state.run;let peak=run.initial;
 const points=[{time:Date.parse(run.startUtc)/1000,value:state.mode==='drawdown'?0:run.initial},...state.curve.map(d=>{
  peak=Math.max(peak,d.equity);return {time:Date.parse(d.date+'T23:59:59Z')/1000,value:state.mode==='drawdown'?100*(d.equity/peak-1):d.equity};
 })];
 backtestChart.line(points,state.mode);
 $('backtest-chart-title').textContent=state.mode==='drawdown'?'Drawdown · daily closes':'Equity curve';
 $('curve-legend').textContent=state.mode==='drawdown'?'Daily equity snapshots · intraday maximum is reported above':`RR 1:${run.rr} · after configured costs`;
 function show(p){$('chart-value').textContent=state.mode==='drawdown'?number(p.value,2)+'%':money(p.value);$('chart-date').textContent=stamp(p.time*1000)+' UTC';}
 show(points.at(-1));backtestChart.onHover=(d,t)=>show({value:d.value,time:t});
}
function fillTradeSelect(){fillSelect($('selected-trade'),[[-1,'Full backtest period'],...state.trades.map((t,i)=>[i,`#${i+1} · ${t.side} · ${stamp(t.entryUtc)} · ${money(t.net)}`])],state.selectedTrade);}
function stopReplay(){if(state.replayTimer)clearInterval(state.replayTimer);state.replayTimer=null;if($('replay-play'))$('replay-play').textContent='Play replay';}
async function loadTradePrice(){
 const ticket=++state.priceTicket,report=state.report?.id,run=state.run?.name;if(!report||!run)return;
 const key=`${report}:${run}:${state.selectedTrade}:${state.btPeriod}`;
 if(state.priceKey===key&&state.priceBars.length){renderTradePrice(true);return;}
 stopReplay();$('backtest-chart-title').textContent='Trade price · historical bid';$('backtest-chart-message').hidden=false;$('backtest-chart-message').textContent='Building candles from cached bid/ask ticks…';
 try {
  const data=await api(`/api/backtest-bars?report=${encodeURIComponent(report)}&run=${encodeURIComponent(run)}&trade=${state.selectedTrade}&period=${state.btPeriod}`);
  if(ticket!==state.priceTicket||state.mode!=='price'||state.report?.id!==report||state.run?.name!==run)return;
  state.btPeriod=data.periodMinutes;$('backtest-period').value=String(data.periodMinutes);state.priceKey=`${report}:${run}:${state.selectedTrade}:${state.btPeriod}`;state.priceBars=data.bars;
  state.replayCursor=Math.max(0,data.bars.length-1);$('replay-cursor').max=state.replayCursor;$('replay-cursor').value=state.replayCursor;
  $('curve-legend').textContent=`M${data.periodMinutes} · bid candles · ${data.missingDays?'partial local cache':'recorded tick cache'} · fills include spread/slippage`;
  renderTradePrice(true);
 }catch(e){if(ticket===state.priceTicket){$('backtest-chart-message').hidden=false;$('backtest-chart-message').textContent=e.message;}}
}
function renderTradePrice(reset=false){
 const bars=state.priceBars.slice(0,(state.replayCursor??state.priceBars.length-1)+1);
 $('backtest-chart-message').hidden=Boolean(bars.length);if(!bars.length){$('backtest-chart-message').textContent='No recorded candles in this range.';return;}
 backtestChart.candles(bars,{reset,fitAll:true});
 const t=state.trades[state.selectedTrade],last=bars.at(-1),period=state.btPeriod*60;
 const levels=t?[{price:t.Entry??t.entry,title:'Entry',color:'#c0c9cf'},{price:t.Stop??t.stop,title:'SL',color:'#e7868b'},{price:t.Target??t.target,title:'TP',color:'#7bd3a7'}]:[];
 const markers=t?[{time:Math.floor(Date.parse(t.entryUtc)/1000/period)*period,position:t.side==='BUY'?'belowBar':'aboveBar',shape:t.side==='BUY'?'arrowUp':'arrowDown',color:'#d4b477',text:'Entry'},{time:Math.floor(Date.parse(t.exitUtc)/1000/period)*period,position:t.side==='BUY'?'aboveBar':'belowBar',shape:'circle',color:t.net>=0?'#7bd3a7':'#e7868b',text:`Exit ${t.reason}`}]:[];
 backtestChart.trade(levels,markers);$('chart-value').textContent=number(last.close,2)+' USD/oz';$('chart-date').textContent=stamp(last.time*1000)+' UTC';$('replay-controls').hidden=bars.length<2&&!state.priceBars.length;
 $('replay-time').textContent=`${state.replayCursor+1} / ${state.priceBars.length} bars · ${stamp(last.time*1000)} UTC`;
 backtestChart.onHover=d=>{$('chart-value').textContent=number(d.close,2)+' USD/oz';};
}
function filteredTrades() {return state.trades.filter(t=>($('trade-session').value==='all'||t.session===$('trade-session').value)&&($('trade-side').value==='all'||t.side===$('trade-side').value));}
function renderTrades() {
 const trades=filteredTrades(),size=20,pages=Math.max(1,Math.ceil(trades.length/size));state.tradePage=Math.max(0,Math.min(state.tradePage,pages-1));
 const selected=trades.slice(state.tradePage*size,(state.tradePage+1)*size);
 $('trades-body').innerHTML=selected.map(t=>`<tr tabindex="0" data-trade="${state.trades.indexOf(t)}"><td>${esc(stamp(t.entryUtc))}</td><td>${t.session==='NewYork'?'New York':esc(t.session)}</td><td class="${t.side==='BUY'?'positive':'negative'}">${esc(t.side)}</td><td>${number(t.volumeOz,0)}</td><td>${number(t.Entry??t.entry,2)}</td><td>${number(t.exit,2)}</td><td>${money(t.commission)}</td><td>${money(t.swap)}</td><td class="${t.net<0?'negative':'positive'}">${money(t.net)}</td><td>${esc(t.reason)}</td></tr>`).join('')||'<tr><td colspan="10">No matching trades.</td></tr>';
 for(const row of $('trades-body').querySelectorAll('[data-trade]')){const choose=()=>{state.selectedTrade=Number(row.dataset.trade);$('selected-trade').value=String(state.selectedTrade);state.mode='price';navigate('backtests');for(const b of document.querySelectorAll('[data-curve]'))b.classList.toggle('active',b.dataset.curve==='price');drawChart();};row.onclick=choose;row.onkeydown=e=>{if(e.key==='Enter'){choose();}};}
 $('trade-page-label').textContent=`${trades.length} trades · Page ${state.tradePage+1} of ${pages}`;$('trades-prev').disabled=state.tradePage===0;$('trades-next').disabled=state.tradePage>=pages-1;
}
function exportTrades() {
 if(!state.run||state.loadedRun!==`?report=${encodeURIComponent(state.report.id)}&run=${encodeURIComponent(state.run.name)}`||!state.trades.length){notify('Wait for the selected run to finish loading.');return;}
 const trades=filteredTrades(),fields=Object.keys(trades[0]||{}),csv=[fields,...trades.map(t=>fields.map(k=>t[k]))].map(row=>row.map(v=>'"'+String(v??'').replace(/"/g,'""')+'"').join(',')).join('\n');
 const url=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));const link=document.createElement('a');link.href=url;link.download=state.run.name+'-trades.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function configuration() {
 const form=$('test-form'),data=new FormData(form),config={};
 for(const [key,value]of data)config[key]=['start','end'].includes(key)?value:Number(value);
 for(const key of ['asia','newYork','swap'])config[key]=form.elements[key].checked;
 return config;
}
function fillForm(config) {
 const form=$('test-form');for(const [key,value]of Object.entries(config||{})){const normalized=key[0].toLowerCase()+key.slice(1),el=form.elements[normalized];if(!el)continue;if(el.type==='checkbox')el.checked=Boolean(value);else el.value=value;}
}
function openDrawer(fromRun=false) {
 state.returnFocus=document.activeElement;
 $('form-error').hidden=true;
 if(fromRun&&state.run){const r=state.run;fillForm({start:r.startUtc.slice(0,10),end:r.endUtcExclusive.slice(0,10),capital:r.initial,rr:r.rr,slippage:r.slippageUsdOz,riskPercent:r.riskPercent??.25,maxDrawdownPercent:r.maxDrawdownPercent??5,...state.report.data.config});}
 else if(state.preset)fillForm(state.preset);
 else if(state.run)fillForm({start:state.run.startUtc.slice(0,10),end:state.run.endUtcExclusive.slice(0,10),capital:state.run.initial,rr:state.run.rr,riskPercent:state.run.riskPercent??.25});
 $('test-drawer').hidden=$('drawer-backdrop').hidden=false;setTimeout(()=>$('test-form').elements.start.focus(),20);
}
function closeDrawer() {$('test-drawer').hidden=$('drawer-backdrop').hidden=true;(state.returnFocus||$('new-test-button')).focus();}
async function submitConfig(path) {
 if(state.readOnly){notify('Read-only preview. Submit research after deployment.');return;}
 const form=$('test-form');if(!form.reportValidity())return;
 $('form-error').hidden=true;$('run-backtest').disabled=$('save-preset').disabled=true;
 try {
  state.csrf=(await api('/api/session')).csrf;
  const config=configuration(),result=await api(path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify(config)});
  if(path==='/api/presets'){state.preset=config;renderPreset();notify('Preset saved locally. Execution settings are unchanged.');}
  else{state.pendingJob=result.id;notify('Backtest running. Results will appear automatically.');}
  closeDrawer();await refresh();
 }catch(e){$('form-error').textContent=e.message;$('form-error').hidden=false;}
 finally{$('run-backtest').disabled=$('save-preset').disabled=false;}
}
function renderPreset() {
 const p=state.preset;if(!p)return;
 const rr=p.rr??p.RR,cap=p.capital??p.Capital,risk=p.riskPercent??p.RiskPercent;
 $('preset-summary').textContent=`RR 1:${rr} · ${money(cap,0)} capital · ${risk}% risk / trade. Saved for research; not applied to execution.`;
}
let marketBusy=false;
async function loadAccount(showError=false){return loadMarket(showError);}
function aggregateBars(bars,minutes){const output=[];for(const b of bars){const time=Math.floor(b.time/(minutes*60))*minutes*60,p=output.at(-1);if(p&&p.time===time){p.high=Math.max(p.high,b.high);p.low=Math.min(p.low,b.low);p.close=b.close;p.volume+=b.volume||0;}else output.push({...b,time});}return output;}
async function loadMarket(showError=false){
 if(marketBusy)return;marketBusy=true;
 try {
  let m=await api('/api/market');let reset=false;if(m.account?.id!==state.market?.account?.id){state.baseBars.clear();state.historyVersion='';reset=true;}
  if(m.historyVersion&&m.historyVersion!==state.historyVersion){const full=await api('/api/market/history');if(full.account?.id===m.account?.id&&full.historyVersion){m=full;state.baseBars=new Map(full.bars.map(b=>[b.time,b]));state.historyVersion=full.historyVersion;reset=true;}}
  else for(const b of m.bars)state.baseBars.set(b.time,b);
  state.market=m;renderMarket();renderLiveChart(reset);
 }catch(e){if(state.market)state.market={...state.market,state:'reconnecting',message:e.message};$('market-status').textContent='DISCONNECTED';$('market-status').className='negative';if(showError)notify(e.message,true);}
 finally{marketBusy=false;}
}
function renderMarket(){
 const m=state.market;if(!m)return;const a=m.summary;
 if(a){$('account-login').textContent=a.login;$('account-label').textContent=`FxPro #${a.login}`;$('account-balance').textContent=money(a.balance);$('account-equity').textContent=money(a.equity);$('account-pnl').textContent=money(a.unrealized);setColor($('account-pnl'),a.unrealized);$('account-positions').textContent=a.positions;$('snapshot-time').textContent=stamp(a.capturedUtc)+' UTC · sampled ~2s';}
 $('live-bid').textContent=number(m.bid,2);$('live-ask').textContent='Ask '+number(m.ask,2);
 $('position-title').textContent=`Position (${a?m.positions.length:'—'})`;
 const p=m.positions[0];$('position-empty').textContent=a?'No open XAUUSD position.':'Waiting for position snapshot…';$('position-empty').hidden=Boolean(p);$('position-detail').hidden=!p;$('position-side').textContent=p?.side||(a?'FLAT':'UNKNOWN');$('position-side').className='side-label '+(p?.side==='SELL'?'negative':p?'positive':'');
 if(p){$('position-size').textContent=number(p.volumeOz,2)+' oz';$('position-entry').textContent=number(p.entry,2);$('position-sl').textContent=p.stopLoss?number(p.stopLoss,2):'MISSING';$('position-tp').textContent=p.takeProfit?number(p.takeProfit,2):'MISSING';$('position-pnl').textContent=money(p.netPnl);setColor($('position-pnl'),p.netPnl??0);$('position-opened').textContent=stamp(p.openedUtc);}
 $('journal-date').textContent=new Date().toISOString().slice(0,10)+' · UTC';
 $('journal-body').innerHTML=m.events.map(e=>`<tr><td>${esc(stamp(e.time))}</td><td>${esc(e.event)}</td><td>XAUUSD</td><td>${esc(e.detail)}</td></tr>`).join('')||'<tr><td colspan="4">No broker fills in the recent history window.</td></tr>';
 updateMarketClock();
}
function updateMarketClock(){
 const m=state.market;if(!m)return;
 const age=m.quoteUtc?(Date.now()-Date.parse(m.quoteUtc))/1000:Infinity;
 const fresh=m.state==='connected'&&age>=0&&age<5;
 $('quote-status').textContent=fresh?'STREAMING':m.state==='connected'?'QUOTE STALE':m.state.toUpperCase();$('quote-status').classList.toggle('idle',!fresh);
 $('market-status').textContent=fresh?'CONNECTED · '+age.toFixed(1)+'s':m.state==='connected'?'QUOTE STALE':m.state.toUpperCase();$('market-status').className=fresh?'positive':'negative';
 $('execution-quote').textContent=m.quoteUtc?stamp(m.quoteUtc)+' UTC · '+(Number.isFinite(age)?Math.max(0,age).toFixed(1)+'s old':''):'Waiting for broker quotes';
 $('quote-spread').textContent=m.ask!=null&&m.bid!=null?'Spread $'+number(m.ask-m.bid,2)+'/oz · P&L ~2s':'Account P&L sampled every 2s';
 const accountAge=m.summary?(Date.now()-Date.parse(m.summary.capturedUtc))/1000:Infinity;
 $('account-equity').classList.toggle('stale',accountAge>8);$('account-pnl').classList.toggle('stale',accountAge>8);
 if(accountAge>8&&m.summary)$('snapshot-time').textContent='STALE · '+stamp(m.summary.capturedUtc)+' UTC';
}
function renderLiveChart(reset=false){
 if(!liveChart)return;const m=state.market,bars=aggregateBars([...state.baseBars.values()].sort((a,b)=>a.time-b.time),state.livePeriod);
 $('live-chart-message').hidden=Boolean(bars.length);if(!bars.length){$('live-chart-message').textContent=m?.message||'Connecting to FxPro market data…';return;}
 liveChart.candles(bars,{reset});const p=m?.positions[0];
 liveChart.trade(p?[{price:p.entry,title:'Entry',color:'#bfc8ce'},{price:p.stopLoss,title:'SL',color:'#e7868b'},{price:p.takeProfit,title:'TP',color:'#7bd3a7'}]:[]);
 $('live-history-caption').textContent='Broker M1 history · aggregated M'+state.livePeriod+' · UTC';
 liveChart.onHover=d=>{$('live-ohlc').textContent=`O ${number(d.open,2)}  H ${number(d.high,2)}  L ${number(d.low,2)}  C ${number(d.close,2)} · tick activity`;};
}
let refreshing=false;
async function refresh() {
 if(refreshing)return;refreshing=true;const executionVersion=state.executionVersion;
 try {
  const [status,reports]=await Promise.all([api('/api/status'),api('/api/reports')]);state.status=status;state.readOnly=Boolean(status.readOnly);
  if(executionVersion===state.executionVersion&&!state.executionAction)renderExecution(status.execution);
  $('progress-banner').hidden=!status.jobs.some(j=>j.state==='running');
  $('api-pill').innerHTML=`<i></i>${status.authorized?'API READY':'CONNECT API'}`;$('api-pill').classList.toggle('warning',!status.authorized);$('settings-access').textContent=status.authorized?'Authorized':'Not connected';
  const running=status.jobs.find(j=>j.state==='running'),complete=status.fullReportReady;
  $('progress-banner').classList.toggle('complete',complete&&!running);
  $('progress-title').textContent=running?'Custom backtest running':complete?'Research data and replay complete':'Preparing tick data & running replay';
  $('progress-detail').textContent=running?`${running.start} → ${running.end} · RR 1:${running.rr}`:complete?'Results include costs and risk controls. Review before execution.':`FxPro XAUUSD · completed through ${status.lastDay??'—'}`;
  $('progress-count').textContent=`${Math.min(status.dataDays,120)} / 120 days`;$('progress-fill').style.width=Math.min(100,status.dataDays/120*100)+'%';
  const changed=reports.map(r=>r.id).join('|')!==state.reports.map(r=>r.id).join('|');state.reports=reports;$('report-count').textContent=reports.length;
  if(changed){const old=state.report?.id;fillSelect($('report-select'),reports.map(r=>{const range=fullRange(r);return [r.id,(r.id.startsWith('custom')?'RR 1:'+r.data.results[0].rr+' · risk '+r.data.results[0].riskPercent+'% · min SL $'+(r.data.config?.MinimumStop??r.data.config?.minimumStop??2):'FxPro')+' · '+periodLabel(range.start,range.end)];}),old);chooseReport(!state.userReport&&reports.some(r=>r.id==='fxpro-20260101-20260501')?'fxpro-20260101-20260501':old);}
  if(!reports.length){$('empty-state').hidden=false;$('result-content').hidden=true;}
  if(state.pendingJob){const job=status.jobs.find(j=>j.id===state.pendingJob);if(job?.state==='completed'){state.userReport=true;chooseReport(job.id);notify('Backtest complete. Select the run to inspect its trades.');state.pendingJob=null;navigate('backtests');}else if(job?.state==='failed'){notify('Backtest failed. Check the configuration and available data.',true);state.pendingJob=null;}}
 }catch(e){if(executionVersion===state.executionVersion&&!state.executionAction){$('bot-pill').textContent='DISCONNECTED';$('bot-pill').classList.add('idle');notify('Dashboard disconnected. The execution service may still be running.',true);}}
 finally{refreshing=false;}
}
for(const button of document.querySelectorAll('[data-page]'))button.onclick=()=>navigate(button.dataset.page);
$('execution-settings').onclick=()=>navigate('settings');$('report-select').onchange=()=>{state.userReport=true;chooseReport($('report-select').value);};
for(const id of ['period-select','capital-select','cost-select'])$(id).onchange=chooseFilters;
for(const button of document.querySelectorAll('[data-curve]'))button.onclick=()=>{state.mode=button.dataset.curve;for(const other of document.querySelectorAll('[data-curve]'))other.classList.toggle('active',other===button);drawChart();};
for(const id of ['trade-session','trade-side'])$(id).onchange=()=>{state.tradePage=0;renderTrades();};
$('trades-prev').onclick=()=>{state.tradePage--;renderTrades();};$('trades-next').onclick=()=>{state.tradePage++;renderTrades();};
$('export-button').onclick=exportTrades;$('refresh-account').onclick=()=>loadAccount(true);
$('new-test-button').onclick=()=>openDrawer();$('edit-preset').onclick=()=>openDrawer();$('use-preset').onclick=()=>openDrawer(true);
$('close-drawer').onclick=$('drawer-backdrop').onclick=closeDrawer;
document.addEventListener('keydown',e=>{if($('test-drawer').hidden)return;if(e.key==='Escape')closeDrawer();if(e.key==='Tab'){const list=[...$('test-drawer').querySelectorAll('button:not(:disabled),input:not(:disabled),select:not(:disabled)')];const first=list[0],last=list.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}});
$('test-form').onsubmit=e=>{e.preventDefault();submitConfig('/api/backtests');};$('save-preset').onclick=()=>submitConfig('/api/presets');
window.addEventListener('hashchange',()=>navigate(location.hash.slice(1)));
function tickClock(){updateBotPill();updateMarketClock();$('utc-clock').textContent=new Date().toLocaleTimeString('en-GB',{timeZone:'UTC',hour12:false})+' UTC';}tickClock();setInterval(tickClock,1000);
(async()=>{liveChart=new FinancialChart($('live-chart'));backtestChart=new FinancialChart($('backtest-chart'));if(phoneAccess&&!phoneSession){location.replace('/pair');return;}navigate(location.hash.slice(1)||'overview');try{state.csrf=(await api('/api/session')).csrf;state.preset=await api('/api/preset');renderPreset();}catch(e){notify(e.message,true);}await refresh();loadMarket();setInterval(refresh,10000);setInterval(loadMarket,2000);})();

// OAuth is completed on the desktop, where its registered loopback callback runs.
if(!['localhost','127.0.0.1'].includes(location.hostname)) {
  for(const link of document.querySelectorAll('a[href="http://localhost:8787/"]')) {
    link.href='#settings';link.removeAttribute('target');link.setAttribute('aria-label','Manage the connection from your desktop');
    if(link.classList.contains('button'))link.textContent='Reconnect on desktop';
  }
}

function executionSummary(c) {
 return `RR 1:${c.rr} · Risk ${c.riskPercent}% · Balance DD halt ${c.maxDrawdownPercent}% · Min SL $${c.minimumStop}/oz · Spread ×${c.spreadMultiplier} · ${[c.asia?'Asia':'',c.newYork?'New York':''].filter(Boolean).join(' + ')}`;
}
function renderExecution(data) {
 if(!data)return;state.execution=data;
 const s=data.status,c=data.config,active=data.active;
 $('execution-title').textContent=s.state==='running'?'Bot is running':`Bot ${s.state}`;
 $('execution-message').textContent=s.message;
 $('execution-config').textContent=c?`Applied to ${c.account.broker} #${c.account.login}: ${executionSummary(c)}`:'No execution config applied.';
 $('execution-start').hidden=active;$('execution-stop').hidden=!active;
 $('execution-start').disabled=state.readOnly||s.state==='offline'||active||!c||Boolean(state.executionAction);
 $('execution-stop').disabled=state.readOnly||!active||state.executionAction==='stop';
 $('execution-apply').disabled=state.readOnly||active||Boolean(state.executionAction)||!state.executionSource||!$('execution-account').value;
 $('execution-account').disabled=active;
 $('execution-heartbeat').textContent=s.heartbeatUtc?stamp(s.heartbeatUtc)+' UTC':'—';
 // Quote freshness is supplied by the independent read-only market stream.
 $('execution-profile').textContent=s.profileDate||(s.state==='warming'?'Loading history…':'—');
 $('execution-dd').textContent=s.drawdownPercent==null?'—':number(s.drawdownPercent,2)+'%';
 $('execution-order').textContent=s.lastOrder?'Last order reference: '+s.lastOrder:'';
 $('settings-execution').textContent=s.state;
 updateBotPill();
}
function updateBotPill() {
 const data=state.execution;if(!data)return;
 const s=data.status,age=Date.now()-Date.parse(s.heartbeatUtc);
 const alive=data.active&&!state.executionAction&&s.state==='running'&&s.heartbeatUtc&&age>=0&&age<15000;
 $('bot-pill').textContent=state.executionAction==='stop'&&data.active?(s.state==='stopping'?'STOPPING':'STOP REQUESTED'):alive?'LIVE':data.active&&s.state==='running'?'DISCONNECTED':s.state.toUpperCase();
 $('bot-pill').classList.toggle('idle',!alive);
 $('bot-pill').classList.toggle('warning',s.state==='fault'||s.state==='halted');
}
async function executionPost(action,body) {
 const version=++state.executionVersion;
 const {csrf}=await api('/api/session');
 const result=await api('/api/execution/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(body)});
 if(version===state.executionVersion)renderExecution(result);return result;
}
async function loadExecutionAccounts() {
 $('execution-load').disabled=true;
 try {
  const accounts=await api('/api/execution/accounts');
  fillSelect($('execution-account'),[['','Select an account'],...accounts.map(a=>[String(a.id),`${a.broker} #${a.login}`])],state.execution?.config?.account.id);
  if(!accounts.length)notify('No authorized FxPro account. Manage the cTrader connection to grant access.',true);
  renderExecution(state.execution);
 }catch(e){notify(e.message,true);}
 finally{$('execution-load').disabled=false;}
}
$('execution-load').onclick=loadExecutionAccounts;
$('execution-account').onchange=()=>renderExecution(state.execution);
$('apply-to-bot').onclick=async()=>{
 if(!state.report||!state.run)return;
 state.executionSource={report:state.report.id,run:state.run.name};
 const raw=state.report.data.config||{},custom=Object.fromEntries(Object.entries(raw).map(([k,v])=>[k[0].toLowerCase()+k.slice(1),v]));
 const c={rr:state.run.rr,riskPercent:custom.riskPercent??.25,maxDrawdownPercent:custom.maxDrawdownPercent??5,minimumStop:custom.minimumStop??2,spreadMultiplier:custom.spreadMultiplier??1.5,asia:custom.asia??true,newYork:custom.newYork??true};
 $('execution-source').textContent=`Selected backtest: ${periodLabel(state.run.startUtc,state.run.endUtcExclusive)} · ${executionSummary(c)}`;
 navigate('settings');await loadExecutionAccounts();$('execution-account').focus();
};
$('execution-apply').onclick=async()=>{
 $('execution-apply').disabled=true;
 try{await executionPost('apply',{...state.executionSource,accountId:Number($('execution-account').value)});notify('Config applied. Review it, then press Start to enable orders.');await loadAccount();}
 catch(e){notify(e.message,true);renderExecution(state.execution);}
};
$('execution-start').onclick=async()=>{
 if(state.readOnly)return;const c=state.execution?.config;if(!c)return;
 if(!confirm(`Start actual order routing on ${c.account.broker} account #${c.account.login}?\n\n${executionSummary(c)}\n\nOpen positions remain protected by broker SL/TP when you stop.`))return;
 $('execution-start').disabled=true;
 try{await executionPost('start',{revision:c.revision,accountLogin:c.account.login});}
 catch(e){notify(e.message,true);renderExecution(state.execution);}
};
async function stopExecution() {
 if(state.readOnly||state.executionAction==='stop')return;
 state.executionAction='stop';
 $('execution-stop').textContent='Stopping…';
 renderExecution(state.execution);
 try {
  let result=await executionPost('stop',{});
  notify('Stop accepted. Waiting for worker confirmation.');
  const deadline=Date.now()+60000;
  while(result.active&&Date.now()<deadline) {
   result=await api('/api/execution');
   renderExecution(result);
   if(result.active)await new Promise(resolve=>setTimeout(resolve,500));
  }
  notify(result.active?'Stop accepted. The worker is still checking an in-flight request.':result.status.state==='idle'?'Bot stopped. No new entries. Existing positions keep their broker SL/TP.':result.status.message,result.status.state==='fault');
 }catch(e){notify('Could not confirm Stop: '+e.message,true);}
 finally {
  state.executionAction=null;
  $('execution-stop').textContent='Stop entries';
  renderExecution(state.execution);
 }
}
$('execution-stop').onclick=stopExecution;

for(const button of document.querySelectorAll('[data-live-period]'))button.onclick=()=>{state.livePeriod=Number(button.dataset.livePeriod);for(const b of document.querySelectorAll('[data-live-period]'))b.classList.toggle('active',b===button);renderLiveChart(true);};
$('fit-live').onclick=()=>liveChart.fit();$('fit-backtest').onclick=()=>backtestChart.fit();
$('selected-trade').onchange=()=>{state.selectedTrade=Number($('selected-trade').value);state.priceKey='';drawChart();};
$('backtest-period').onchange=()=>{state.btPeriod=Number($('backtest-period').value);state.priceKey='';drawChart();};
$('replay-cursor').oninput=()=>{stopReplay();state.replayCursor=Number($('replay-cursor').value);renderTradePrice(true);};
$('replay-play').onclick=()=>{
 if(state.replayTimer){stopReplay();return;}if(!state.priceBars.length)return;
 if(state.replayCursor>=state.priceBars.length-1)state.replayCursor=0;
 $('replay-play').textContent='Pause replay';
 state.replayTimer=setInterval(()=>{state.replayCursor++;if(state.replayCursor>=state.priceBars.length-1){state.replayCursor=state.priceBars.length-1;stopReplay();}$('replay-cursor').value=state.replayCursor;renderTradePrice(false);},400);
};
window.addEventListener('focus',()=>{refresh();loadMarket();});
document.addEventListener('visibilitychange',()=>{if(!document.hidden){refresh();loadMarket();}});
