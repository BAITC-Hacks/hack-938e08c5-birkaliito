import test from 'node:test';
import assert from 'node:assert/strict';
import {historyRun,attachResult} from './api.mjs';

test('backend history is adapted without inventing result points',()=>{
 const run=historyRun({cancel_requested:false,job:{job_id:'job-1',status:'completed',updated_at:'2026-01-01T00:00:00Z'},request:{forecast_origin:'2026-01-31T18:00:00Z',horizon_hours:24,turbine_ids:[1,2],model_version:'m1',data_mode:'fixture'}});
 assert.equal(run.key,'job-1');assert.deepEqual(run.turbines,['1','2']);assert.deepEqual(run.points,[]);assert.equal(run.remote,true);
});

test('result adapter keeps canonical quantiles and normalizes turbine ids for UI',()=>{
 const run={};
 attachResult(run,{forecast_origin:'2026-01-31T18:00:00Z',horizon_hours:24,model_version:'m1',data_mode:'fixture',points:[{turbine_id:1,power_mean:.4,q10:.2,q50:.3,q90:.6}]});
 assert.equal(run.points[0].turbine_id,'1');assert.equal(run.points[0].q90,.6);assert.deepEqual(run.turbines,['1']);
});
