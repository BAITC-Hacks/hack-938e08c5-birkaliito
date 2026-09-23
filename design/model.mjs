/** UI-only presentation helpers. NOT an API mock, DTO or official fixture.
 * Replace presentation data through an adapter to baseline_contracts when delivered.
 * No request is sent to Go/Python; no model or weather service is invoked.
 */
export const ZONE = 'Asia/Almaty';
export const STATE_LABELS = {
  initial:'До запуска', submitting:'Отправка запроса', queued:'В очереди', running:'Выполняется',
  completed:'Завершён', degraded:'Завершён · degraded', failed:'Ошибка задания',
  cancel_requested:'Отмена запрошена', cancelled:'Отменён', python_unavailable:'Python недоступен',
  llm_unavailable:'LLM недоступна', metrics_unavailable:'Метрики недоступны',
};
export function csvTime(value) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone:ZONE, year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit',
    minute:'2-digit', second:'2-digit', hourCycle:'h23',
  }).formatToParts(new Date(value)).map(p=>[p.type,p.value]));
  return `${parts.year}-${parts.month}-${parts.day} ${Number(parts.hour)}:${parts.minute}:${parts.second}`;
}
export const originDay = origin => csvTime(origin).split(' ')[0];
export const num = (value, digits=3) => Number.isFinite(value) ? value.toLocaleString('ru-RU',{minimumFractionDigits:digits,maximumFractionDigits:digits}) : '—';
export function illustrationPoints(origin,horizon,turbines) {
  const start=Date.parse(origin)+3600000;
  return Array.from({length:horizon},(_,h)=>turbines.map(id=>{
    const mean=Math.max(.025,Math.min(.92,.45+.21*Math.sin((h-3)/6)+.075*Math.cos(h/2.4)+(id==='2'?-.055:0)));
    const halfWidth=.075+h*.0018;
    return {valid_time:new Date(start+h*3600000).toISOString(),interval_end:new Date(start+(h+1)*3600000).toISOString(),turbine_id:id,power_mean:mean,q10:Math.max(0,mean-halfWidth),q50:Math.max(0,mean-.013),q90:Math.min(1,mean+halfWidth)};
  })).flat();
}
export function makePreview({origin='2026-01-31T23:00:00+05:00',horizon=48,turbines=['1','2'],stage='completed',key='preview-001'}={}) {
  return {key,origin,horizon,turbines,stage,quality:stage==='degraded'?'degraded':'passed',explanation:'unavailable',executedAt:null,model:'UI illustration',mode:'synthetic',points:illustrationPoints(origin,horizon,turbines)};
}
export function statusOf(stage) {
  if(['degraded','llm_unavailable','metrics_unavailable'].includes(stage))return 'completed';
  if(stage==='python_unavailable')return 'failed';
  if(stage==='cancel_requested')return 'running';
  return stage;
}
export const hasResult = run => statusOf(run.stage)==='completed';
export function filterHistory(rows,{from='',to='',turbine='all',status='all',mode='all',sort='desc'}={}) {
  return rows.filter(r=>(!from||originDay(r.origin)>=from)&&(!to||originDay(r.origin)<=to)&&(turbine==='all'||r.turbines.includes(turbine))&&(status==='all'||statusOf(r.stage)===status)&&(mode==='all'||r.mode===mode)).sort((a,b)=>(Date.parse(a.origin)-Date.parse(b.origin))*(sort==='asc'?1:-1));
}
export function energyScenario(points,{capacities,plan,confirmed,turbines}) {
  if(!confirmed)throw new Error('Подтвердите допущение: нормализация относительно номинальной мощности.');
  if(!Number.isFinite(plan)||plan<0)throw new Error('План должен быть неотрицательным числом.');
  if(turbines.some(t=>!Number.isFinite(capacities[t])||capacities[t]<=0))throw new Error('Укажите положительную номинальную мощность каждой выбранной турбины.');
  const groups=new Map();
  for(const p of points){if(!turbines.includes(p.turbine_id))continue;const group=groups.get(p.valid_time)||[];group.push(p);groups.set(p.valid_time,group);}
  const rows=[...groups.entries()].sort((a,b)=>Date.parse(a[0])-Date.parse(b[0])).map(([time,group])=>{
    if(group.length!==turbines.length||new Set(group.map(p=>p.turbine_id)).size!==turbines.length)return {time,complete:false};
    const durations=group.map(p=>(Date.parse(p.interval_end)-Date.parse(p.valid_time))/3600000);
    if(group.some(p=>!Number.isFinite(p.power_mean))||durations.some(d=>d!==1))return {time,complete:false};
    const power=group.reduce((sum,p)=>sum+p.power_mean*capacities[p.turbine_id],0);
    const energy=power; // Each verified interval is exactly 1h. Average kW × 1h.
    return {time,complete:true,power,energy,plan,deficit:Math.max(plan-energy,0),surplus:Math.max(energy-plan,0)};
  });
  const complete=rows.filter(r=>r.complete);
  return {rows,completeHours:complete.length,missingHours:rows.length-complete.length,total:complete.reduce((a,r)=>({energy:a.energy+r.energy,plan:a.plan+r.plan,deficit:a.deficit+r.deficit,surplus:a.surplus+r.surplus}),{energy:0,plan:0,deficit:0,surplus:0})};
}
export function previewCSV(run) {
  const head=['data_mode','origin','valid_time','interval_end','turbine_id','power_mean','q10','q50','q90'];
  return [head.join(','),...run.points.map(p=>['synthetic_ui_illustration',run.origin,p.valid_time,p.interval_end,p.turbine_id,...['power_mean','q10','q50','q90'].map(k=>p[k].toFixed(6))].join(','))].join('\r\n');
}
