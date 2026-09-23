import test from 'node:test';
import assert from 'node:assert/strict';
import {WindClient, ApiException} from './.test-build/client.js';

test('creation preserves key; HTTP errors are typed', async () => {
  const previous=globalThis.fetch;
  try {
    globalThis.fetch=async (url,options) => {assert.equal(url,'/api/forecast-runs');assert.equal(options.headers['Idempotency-Key'],'same-operation');return new Response(JSON.stringify({code:'IDEMPOTENCY_CONFLICT',message:'Conflict',request_id:'req-test'}),{status:409});};
    await assert.rejects(new WindClient().createForecast({forecast_origin:'2026-01-31T18:00:00Z',model_version:'fixture-not-trained',data_mode:'fixture'},'same-operation'),e=>e instanceof ApiException&&e.status===409&&e.detail.code==='IDEMPOTENCY_CONFLICT');
  } finally {globalThis.fetch=previous;}
});

test('SSE deduplicates IDs and closes on stream_end', () => {
  const previous=globalThis.EventSource;let instance;
  class Source {listeners=new Map();closed=false;constructor(url){this.url=url;instance=this;}addEventListener(name,callback){this.listeners.set(name,callback);}close(){this.closed=true;}emit(name,data){this.listeners.get(name)({data:JSON.stringify(data)});}}
  try {globalThis.EventSource=Source;let count=0,ended=false;new WindClient().subscribeJobEvents('job-1',{onEvent:()=>count++,onEnd:()=>ended=true});instance.emit('agent_event',{job_id:'job-1',event_id:1});instance.emit('agent_event',{job_id:'job-1',event_id:1});instance.emit('agent_event',{job_id:'job-1',event_id:2});instance.emit('stream_end',{job_id:'job-1',status:'completed'});assert.equal(count,2);assert.equal(ended,true);assert.equal(instance.closed,true);}finally{globalThis.EventSource=previous;}
});

test('polling fallback drains terminal events and never requests cancellation', async () => {
  const oldFetch=globalThis.fetch,oldSource=globalThis.EventSource;const paths=[];let events=0;
  try {globalThis.EventSource=undefined;globalThis.fetch=async url=>{paths.push(url);if(url.includes('/events'))return Response.json([{job_id:'job-1',event_id:4}]);return Response.json({job_id:'job-1',status:'completed'});};await new Promise((resolve,reject)=>new WindClient('',1).subscribeJobEvents('job-1',{onEvent:()=>events++,onEnd:resolve,onError:reject}));assert.equal(events,1);assert.equal(paths.length,2);assert.equal(paths.some(p=>p.includes('cancel')),false);}finally{globalThis.fetch=oldFetch;globalThis.EventSource=oldSource;}
});

test('unmount aborts subscription without cancelling job',()=>{const old=globalThis.EventSource;let closed=0;try{globalThis.EventSource=class{addEventListener(){}close(){closed++;}};const signal=new AbortController();new WindClient().subscribeJobEvents('job-1',{onEvent(){},onEnd(){}},0,signal.signal);signal.abort();assert.equal(closed,1);}finally{globalThis.EventSource=old;}});
