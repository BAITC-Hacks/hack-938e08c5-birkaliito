import test from 'node:test';
import assert from 'node:assert/strict';
import {makePreview,csvTime,filterHistory,visibleSelection,powerOverview,energyScenario,previewCSV,hasResult,statusOf,latestForecast} from './model.mjs';
test('48 hours × 2 turbines; interval boundaries and local CSV time',()=>{
 const r=makePreview();assert.equal(r.points.length,96);
 assert.equal(csvTime(r.points[0].valid_time),'2026-02-01 0:00:00');
 assert.equal(csvTime(r.points.at(-1).interval_end),'2026-02-03 0:00:00');
 assert.notEqual(r.points[0].power_mean,r.points[0].q50);
 for(const p of r.points){assert.ok(p.q10<=p.q50&&p.q50<=p.q90);assert.equal(Date.parse(p.interval_end)-Date.parse(p.valid_time),3600000);}
});
test('home uses latest ready server forecast before any newer UI illustration',()=>{
 const old=makePreview({origin:'2026-01-31T23:00:00+05:00'});
 const demo=makePreview({origin:'2026-02-20T23:00:00+05:00'});
 const remote={...makePreview({origin:'2026-02-01T23:00:00+05:00'}),remote:true,mode:'real',points:[]};
 const pending={...remote,origin:'2026-02-25T23:00:00+05:00',stage:'running'};
 const rows=[old,demo,remote,pending],snapshot=[...rows];
 assert.equal(latestForecast(rows),remote);assert.deepEqual(rows,snapshot);
 assert.equal(latestForecast([old,demo]),demo);
 assert.equal(latestForecast([pending]),null);assert.equal(latestForecast([]),null);
});
test('history dates filter origin, inclusive, not target time; overlapping forecasts survive',()=>{
 const a=makePreview(),b=makePreview({origin:'2026-02-01T23:00:00+05:00'});
 assert.equal(filterHistory([a,b],{from:'2026-01-31',to:'2026-01-31'}).length,1);
 assert.equal(filterHistory([a,b],{from:'2026-02-01',to:'2026-02-01'})[0],b);
 assert.equal(filterHistory([a,b]).length,2);
 assert.equal(filterHistory([a,b],{status:'failed'}).length,0);
});
test('completed with degraded or unavailable LLM still exposes numeric result',()=>{
 for(const stage of ['completed','degraded','llm_unavailable'])assert.ok(hasResult(makePreview({stage})));
 for(const stage of ['queued','running','cancel_requested','failed','cancelled','python_unavailable'])assert.ok(!hasResult(makePreview({stage})));
 assert.equal(statusOf('cancel_requested'),'running');
});
test('energy requires explicit assumptions and positive finite capacities',()=>{
 const points=makePreview().points;
 assert.throws(()=>energyScenario(points,{capacities:{1:100,2:100},plan:40,confirmed:false,turbines:['1','2']}));
 assert.throws(()=>energyScenario(points,{capacities:{1:0,2:100},plan:40,confirmed:true,turbines:['1','2']}));
 assert.throws(()=>energyScenario(points,{capacities:{1:100,2:100},plan:-1,confirmed:true,turbines:['1','2']}));
});
test('zero is valid; aggregate station before computing deficit, do not sum individual deficits',()=>{
 const p={valid_time:'2026-02-01T00:00:00+05:00',interval_end:'2026-02-01T01:00:00+05:00'};
 const result=energyScenario([{...p,turbine_id:'1',power_mean:0},{...p,turbine_id:'2',power_mean:1}],{capacities:{1:100,2:100},plan:80,confirmed:true,turbines:['1','2']});
 assert.equal(result.total.energy,100);assert.equal(result.total.deficit,0);assert.equal(result.total.surplus,20);
 assert.equal(result.completeHours,1);
});
test('missing turbine or invalid interval is not zero-filled',()=>{
 const r=makePreview({horizon:24});
 const options={capacities:{1:100,2:100},plan:80,confirmed:true,turbines:['1','2']};
 const partial=energyScenario(r.points.slice(1),options);assert.equal(partial.completeHours,23);assert.equal(partial.missingHours,1);
 const broken=r.points.map(p=>({...p}));broken[0].interval_end=broken[0].valid_time;
 assert.equal(energyScenario(broken,options).missingHours,1);
});
test('CSV marks synthetic illustration and carries origin + both interval bounds',()=>{
 const csv=previewCSV(makePreview());assert.equal(csv.split('\r\n').length,97);
 assert.ok(csv.includes('synthetic_ui_illustration'));assert.ok(csv.startsWith('data_mode,origin,valid_time,interval_end'));
});
test('merged history never silently changes the selected forecast when filters exclude it',()=>{
 const first=makePreview({key:'first'}),second=makePreview({key:'second',origin:'2026-02-01T23:00:00+05:00'});
 const visible=filterHistory([first,second],{from:'2026-02-01',to:'2026-02-01'});
 assert.equal(visibleSelection(visible,'first'),null);
 assert.equal(visibleSelection(visible,'second'),second);
 assert.equal(visibleSelection([],'second'),null);
});
test('analytics summary keeps turbine statistics separate and counts hours, not rows',()=>{
 const r=makePreview(),s=powerOverview(r.points,r.turbines);
 assert.equal(s.records,96);assert.equal(s.hours,48);assert.equal(s.turbines.length,2);
 assert.notEqual(s.turbines[0].mean,s.turbines[1].mean);
 assert.equal(s.turbines[0].count,48);assert.equal(s.unavailable,0);
 const first=r.points[0];const missing=powerOverview([{...first,power_mean:0},{...first,turbine_id:'2',power_mean:null}],['1','2']);
 assert.equal(missing.turbines[0].min,0);assert.equal(missing.turbines[0].mean,0);
 assert.equal(missing.turbines[1].mean,null);assert.equal(missing.unavailable,1);
 assert.equal(powerOverview([],['1']).turbines[0].max,null);
});
