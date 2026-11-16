import {readFile} from 'node:fs/promises';import assert from 'node:assert/strict';import vm from 'node:vm';
const file=process.argv[2];assert(file,'Pass C# parity output JSON');
const c=vm.createContext({window:{}});vm.runInContext(await readFile(new URL('./assets/price-action.js',import.meta.url),'utf8'),c);
const cases=JSON.parse(await readFile(file,'utf8')),snapshots=new Map();
for(const row of cases){
 if(!snapshots.has(row.file))snapshots.set(row.file,JSON.parse(await readFile(new URL('./assets/'+row.file,import.meta.url),'utf8')));
 const snap=snapshots.get(row.file),s=c.window.paStructure(snap.bars,row.cursor);
 assert.equal(s.regime,row.regime,`${row.file} cursor${row.cursor} regime`);
 assert.equal(JSON.stringify(s.pivots.map(p=>({high:p.type==='high',price:p.price,index:p.index,knownIndex:p.knownIndex}))),JSON.stringify(row.pivots));
 for(const t of row.targets){const b=snap.bars[row.cursor],expected=c.window.paSetup({long:t.buy,low:0,high:0},b.close,snap.rangeUsdOz,s);assert.equal(t.decision.target,expected.target);assert.equal(t.decision.regime,s.regime);}
}
console.log(`PA parity PASS: ${cases.length} causal chart/backend prefixes across ${snapshots.size} snapshots, including all confirmation targets.`);
