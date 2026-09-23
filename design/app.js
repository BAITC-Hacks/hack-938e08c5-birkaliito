import {ZONE,STATE_LABELS,csvTime,num,makePreview,statusOf,hasResult,latestForecast,filterHistory,visibleSelection,powerOverview,energyScenario,previewCSV} from './model.mjs';
import {api,historyRun,attachResult,waitForJob,waitForForecast,downloadBlob} from './api.mjs';

// UI state is adapted at the boundary in api.mjs; backend contracts remain canonical.
const paths={wind:'M3 8h12a3 3 0 1 0-3-3M2 12h17a3 3 0 1 1-3 3M5 16h5a2.5 2.5 0 1 1-2.5 2.5',grid:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',chart:'M3 3v18h18M6 16l4-6 4 3 6-8',clock:'M12 8v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',repeat:'M20 7v5h-5M4 17v-5h5M5.6 7a8 8 0 0 1 13-1L20 8M4 16l1.4 2a8 8 0 0 0 13-1',shield:'m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3ZM8 12l3 3 5-6',spark:'m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6L12 3ZM20 2v4M18 4h4',database:'M20 6c0 2-3.6 3-8 3S4 8 4 6s3.6-3 8-3 8 1 8 3ZM4 6v6c0 2 3.6 3 8 3s8-1 8-3V6M4 12v6c0 2 3.6 3 8 3s8-1 8-3v-6',help:'M9.5 8.5a2.5 2.5 0 0 1 5 0c0 2-2.5 2-2.5 4M12 16h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',info:'M12 11v6M12 7h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',arrow:'M7 17 17 7M7 7h10v10',right:'M4 12h16M15 7l5 5-5 5',close:'m6 6 12 12M6 18 18 6',download:'M12 3v12M7 10l5 5 5-5M4 16v4h16v-4',pin:'M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0ZM14.5 10a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0',bolt:'m13 2-9 12h7l-1 8 10-13h-7l0-7Z',cloud:'M7 18a5 5 0 1 1 .5-10 6 6 0 0 1 11.5 2 4 4 0 0 1 0 8H7Z',play:'m9 5 11 7-11 7V5Z',check:'m5 12 4 4L19 6',warning:'m12 3 10 18H2L12 3ZM12 9v5M12 17h.01',menu:'M4 6h16M4 12h16M4 18h16',file:'M14 3H5v18h14V8l-5-5ZM14 3v5h5M8 12h8M8 16h6',filter:'M4 5h16M7 12h10M10 19h4',turbine:'M12 10V2l-2 2 1 6M13 11l7 4-1-3-5-2M11 12l-7 4 3 1 5-4M11 13l-1 9h4l-1-9M14 11a2 2 0 1 1-4 0 2 2 0 0 1 4 0'};
const icon=name=>`<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name]||paths.info}"/></svg>`;
const $=selector=>document.querySelector(selector);
const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const decorate=()=>document.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML=icon(el.dataset.icon));
const button=(label,action,kind='',symbol='arrow',extra='')=>`<button class="button ${kind}" data-action="${action}" ${extra}>${symbol?icon(symbol):''}<span>${label}</span></button>`;
const pill=(label,kind='neutral',symbol='')=>`<span class="pill ${kind}">${symbol?icon(symbol):''}${label}</span>`;
const field=(label,id,html)=>`<div class="field"><label for="${id}">${label}</label>${html}</div>`;
const detailNote=(id,label,content)=>`<details class="detail-note" id="${id}"><summary>${label}</summary><div>${content}</div></details>`;
const kv=rows=>`<dl class="kv">${rows.map(([k,v])=>`<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl>`;
const empty=(title,text,symbol='database',action='')=>`<div class="empty">${icon(symbol)}<h2>${title}</h2><p>${text}</p>${action}</div>`;
const notice=(title,text,type='',action='')=>`<div class="state-notice ${type}" role="status">${icon(type==='error'?'warning':'info')}<div><h3>${title}</h3><p>${text}</p></div>${action}</div>`;
const stagePill=stage=>pill(STATE_LABELS[stage]||stage,['failed','python_unavailable'].includes(stage)?'error':stage==='degraded'?'warn':statusOf(stage)==='completed'?'ok':'neutral',statusOf(stage)==='completed'?'check':stage==='failed'?'warning':'clock');
let run=makePreview();
const history=[run,makePreview({key:'preview-002',origin:'2026-02-01T23:00:00+05:00'}),makePreview({key:'preview-003',origin:'2026-02-02T23:00:00+05:00',stage:'degraded',horizon:24,turbines:['1']}),makePreview({key:'preview-004',origin:'2026-01-30T23:00:00+05:00',stage:'failed'})];
const state={page:'forecast',reportRunId:run.key,reportTab:'hourly',quantileDetails:false,largeText:false,draft:{origin:'2026-01-31T23:00',horizon:48,turbines:'both'},chartTurbine:'both',tablePage:0,filters:{from:'2026-01-29',to:'2026-02-28',turbine:'all',status:'all',mode:'all',sort:'desc'},energy:null,energyDirty:false,energyInput:{p1:'',p2:'',plan:'',confirmed:false},replay:null,replayDraft:{from:'2026-01-31',to:'2026-02-27',time:'23:00',horizon:48},evaluations:[],evaluationId:'',dataQuality:null};
const backend={available:false,modelVersion:'fixture-not-trained',capabilities:{},message:'Подключение к backend…'};
const runExtras=new Map();
let toastTimer,loadRunSequence=0,navigationVersion=0;
try { state.largeText=localStorage.getItem('aura-large-text')==='true'; } catch {}
let sidebarCollapsed=false,navReturnFocus=true,navigationFocusRequested=false,navOpener=null;
try { sidebarCollapsed=localStorage.getItem('aura-sidebar-collapsed')==='true'; } catch {}
const navMedia=matchMedia('(max-width:800px)');
function syncSidebar(){
 document.body.classList.toggle('sidebar-collapsed',sidebarCollapsed);
 const toggle=$('#sidebar-toggle'),label=sidebarCollapsed?'Развернуть меню':'Свернуть меню';
 toggle.setAttribute('aria-expanded',String(!sidebarCollapsed));toggle.setAttribute('aria-label',label);toggle.title=label;
 toggle.querySelector('.nav-label').textContent=label;
 document.querySelectorAll('[data-action="menu-open"]').forEach(el=>el.setAttribute('aria-expanded',String($('#nav-dialog').open)));
}
function restoreNavigation(){
 const drawer=$('#nav-dialog');if(!drawer.contains($('#sidebar')))return;
 $('#sidebar-dock').append($('#sidebar'));document.body.classList.remove('menu-open');
 document.querySelectorAll('[data-action="menu-open"]').forEach(el=>el.setAttribute('aria-expanded','false'));
 if(navReturnFocus&&navMedia.matches)(navOpener?.isConnected?navOpener:state.page==='home'?$('.home-menu'):$('#mobile-menu'))?.focus();
}
function closeNavigation(returnFocus=true){
 navReturnFocus=returnFocus;
 if($('#nav-dialog').open)$('#nav-dialog').close();
 restoreNavigation();
}
function openNavigation(trigger){
 if(!navMedia.matches)return;
 navOpener=trigger;
 navReturnFocus=true;$('#nav-dialog').append($('#sidebar'));
 document.body.classList.add('menu-open');document.querySelectorAll('[data-action="menu-open"]').forEach(el=>el.setAttribute('aria-expanded','true'));
 $('#nav-dialog').showModal();$('.sidebar-close').focus();
}
$('#nav-dialog').addEventListener('close',restoreNavigation);
$('#nav-dialog').addEventListener('click',e=>{
 if(e.target!==$('#nav-dialog'))return;
 const r=e.target.getBoundingClientRect();
 if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)closeNavigation();
});
navMedia.addEventListener('change',()=>{if(!navMedia.matches)closeNavigation(false);});
const friendlyTime=value=>new Intl.DateTimeFormat('ru-RU',{timeZone:ZONE,day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value));
const qualityText=value=>value==='degraded'?'Есть замечания':'Без замечаний';
function toast(text){$('#toast').textContent=text;$('#toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),4000);}
function modal(title,content,kicker='AURA / ДЕТАЛИ'){ $('#modal-title').textContent=title;$('#modal-kicker').textContent=kicker;$('#modal-body').innerHTML=content;decorate();if(!$('#modal').open)$('#modal').showModal(); }
function closeModal(){$('#modal').close();}
function download(text,name,type='text/csv;charset=utf-8'){const url=URL.createObjectURL(new Blob(['\ufeff',text],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);toast('Скачан файл с пометкой «Демонстрационные данные».');}
function heading(title,subtitle,actions=''){return actions?`<div class="page-actions">${actions}</div>`:'';}
const compactTime=value=>new Intl.DateTimeFormat('ru-RU',{timeZone:ZONE,day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value));
function homePage(){
 const latest=latestForecast(history);
 const demo=!latest?.remote||latest.mode!=='real';
 return `<section class="home-hero" aria-label="AURA — прогноз ветровой энергии">
 <img class="home-image" src="assets/wind-landscape.png" alt="" fetchpriority="high" width="1586" height="992"><div class="home-wash" aria-hidden="true"></div>
 <header class="home-header"><a class="home-logo" href="#home" aria-label="AURA — главная">aura</a><nav class="home-links" aria-label="Разделы AURA"><a href="#forecast">Прогноз</a><a href="#reports">Аналитика</a><a href="#data">Данные</a></nav><a class="home-enter" href="#forecast">Открыть AURA ${icon('arrow')}</a><button class="home-menu" data-action="menu-open" aria-controls="nav-dialog" aria-expanded="false" aria-label="Открыть меню">${icon('menu')}</button></header>
 <div class="home-content"><div class="home-copy"><h1 id="page-title" tabindex="-1">Энергия ветра.<br><span>На шаг вперёд.</span></h1><p>Почасовой прогноз для вашей ВЭС.</p><a class="home-cta" href="#forecast">Открыть прогноз ${icon('arrow')}</a></div>
 <aside class="home-run"><div class="home-run-heading"><h2>Последний выпуск</h2>${pill(demo?'Демо':'Реальные данные','neutral')}</div><p class="home-run-date">${latest?compactTime(latest.origin)+' · Алматы':'Пока нет выпусков'}</p><dl class="home-run-meta"><div><dt>Статус</dt><dd>${latest?STATE_LABELS[latest.stage]||esc(latest.stage):'Нет данных'}</dd></div><div><dt>Турбины</dt><dd>${latest?latest.turbines.map(t=>'Т'+esc(t)).join(' + '):'—'}</dd></div><div><dt>Горизонт</dt><dd>${latest?latest.horizon+' ч':'—'}</dd></div><div><dt>Новый прогноз</dt><dd>${backend.available?'Доступен':'Недоступен'}</dd></div></dl><a class="home-run-link" href="#reports" ${latest?`data-home-run="${esc(latest.key)}"`:''}>Открыть аналитику ${icon('arrow')}</a></aside></div>
 <div class="home-bottom"><dl class="home-stats"><div><dt>Турбины</dt><dd>2</dd></div><div><dt>Горизонт прогноза</dt><dd>24–48<span> ч</span></dd></div><div><dt>Шаг прогноза</dt><dd>1<span> час</span></dd></div></dl><p class="home-disclaimer">${demo?'Демо-данные · не для рабочих решений':'Время выпусков: Алматы'}</p></div></section>`;
}
function stateSelector(){
 if(run.remote)return '';
 return `<details class="developer-tools" id="developer-tools"><summary>Для разработчиков</summary><div class="state-strip">${icon('grid')}<div><b>Демо-состояние</b><p>Не запускает расчёт.</p></div><select aria-label="Состояние макета" id="preview-state">${Object.entries(STATE_LABELS).map(([key,label])=>`<option value="${key}" ${run.stage===key?'selected':''}>${label}</option>`).join('')}</select></div></details>`;
}
function currentNotice(){
 const s=run.stage;
 if(s==='completed')return '';
 if(s==='degraded')return notice('Прогноз готов, но есть замечания','В этом примере использован запасной источник. Перед рабочим решением проверьте сведения о прогнозе.','warn');
 if(s==='llm_unavailable')return notice('Прогноз готов. Текстовое объяснение недоступно','График, таблица и файл с числами по-прежнему доступны.','warn');
 if(s==='metrics_unavailable')return notice('Прогноз готов. Оценка точности пока отсутствует','Отчёт появится в разделе «Качество модели», когда будет проведена проверка.','warn');
 if(s==='python_unavailable')return notice('Сервис расчёта временно недоступен','Попробуйте создать новый расчёт позже. Предыдущие выпуски остаются в истории.','error',button('Новый расчёт','new-preview','','repeat'));
 if(s==='failed')return notice('Не удалось рассчитать прогноз','Результат не получен. Попробуйте новый расчёт или откройте предыдущий выпуск.','error',button('Новый расчёт','new-preview','','repeat'));
 if(s==='cancelled')return notice('Расчёт отменён','Уже завершённые выпуски сохранены в разделе «История и анализ».');
 if(s==='initial')return notice('Начните с даты и времени','Выберите, на какой момент выпускать прогноз. Он охватит следующие 24 или 48 часов.');
 if(s==='cancel_requested')return notice('Ожидаем подтверждения отмены','Расчёт считается активным, пока сервер не подтвердит отмену.','warn');
 return notice(s==='queued'?'Расчёт в очереди':s==='submitting'?'Запрос отправляется':'Идёт расчёт',
 run.remote?'Состояние получено от backend. Закрытие вкладки не отменяет расчёт.':'Показано состояние локальной иллюстрации.',
 '',s==='submitting'?'':button('Отменить расчёт','cancel','ghost','close'));
}
function config(){
 return `<section class="card pad config-card">
 <form id="forecast-form" class="run-config" aria-label="Новый прогноз">
 ${field('Выпуск · Алматы','origin',`<input id="origin" type="datetime-local" value="${state.draft.origin}" min="2026-01-01T00:00" max="2026-02-28T23:00" step="3600" required>`)}
 <div class="field"><label>Горизонт</label><div class="segmented" role="group" aria-label="Горизонт прогноза">${[24,48].map(h=>`<button type="button" data-horizon="${h}" aria-pressed="${state.draft.horizon===h}" class="${state.draft.horizon===h?'active':''}">${h} ч</button>`).join('')}</div></div>
 ${field('Турбины','turbines',`<select id="turbines"><option value="both" ${state.draft.turbines==='both'?'selected':''}>Обе турбины</option><option value="1" ${state.draft.turbines==='1'?'selected':''}>Турбина 1</option><option value="2" ${state.draft.turbines==='2'?'selected':''}>Турбина 2</option></select>`)}
 <button id="forecast-submit" class="button primary" type="submit" ${!backend.available||['queued','running','cancel_requested','submitting'].includes(run.stage)?'disabled':''}>${icon('play')}<span>Создать прогноз</span></button></form>
 ${!backend.available?'<p class="config-status" role="status">Сервис расчёта недоступен</p>':''}
 ${detailNote('model-options','О расчёте',`<p>Выпуск — момент, на который доступны входные данные. Новые настройки применяются после запуска.</p><p>${esc(backend.message)} Модель: ${esc(backend.modelVersion)}. Режим данных: fixture.</p>`)}</section>`;
}
function chart(){
 const ids=state.chartTurbine==='both'?run.turbines:run.turbines.filter(t=>t===state.chartTurbine);
 const W=780,H=224,left=30,right=765,top=14,bottom=190;
 const x=i=>left+i/(run.horizon-1)*(right-left), y=v=>bottom-v*(bottom-top);
 const series=ids.map(id=>({id,rows:run.points.filter(p=>p.turbine_id===id)}));
 const line=(rows,key)=>rows.map((p,i)=>`${i?'L':'M'}${x(i).toFixed(2)},${y(p[key]).toFixed(2)}`).join(' ');
 const svg=`<svg class="forecast-chart" viewBox="0 0 ${W} ${H}" role="img" aria-labelledby="forecast-chart-title"><title id="forecast-chart-title">Иллюстрация нормализованной мощности: среднее и q10–q90 по турбинам, не реальные результаты</title>${[0,.25,.5,.75,1].map(v=>`<line x1="${left}" x2="${right}" y1="${y(v)}" y2="${y(v)}" stroke="#CBD5CC" stroke-dasharray="3 6" stroke-width=".7"/><text x="0" y="${y(v)+3}" fill="#52675D" font-size="14">${num(v,v===0||v===1?0:2)}</text>`).join('')}${series.map(({id,rows})=>`<path d="${line(rows,'q90')} ${[...rows].reverse().map((p,i)=>`L${x(rows.length-i-1)},${y(p.q10)}`).join(' ')} Z" fill="${id==='1'?'#24634E':'#426889'}" opacity="${id==='1'?'.10':'.045'}"/><path d="${line(rows,'power_mean')}" fill="none" stroke="${id==='1'?'#24634E':'#426889'}" stroke-width="2.4" ${id==='2'?'stroke-dasharray="6 5"':''}/>`).join('')}${[0,Math.floor(run.horizon/4),Math.floor(run.horizon/2),Math.floor(run.horizon*3/4),run.horizon-1].map(i=>`<text x="${x(i)}" y="216" text-anchor="${i===0?'start':i===run.horizon-1?'end':'middle'}" fill="#52675D" font-size="14">${csvTime(run.points[i*run.turbines.length].valid_time).slice(5,10)} · ${csvTime(run.points[i*run.turbines.length].valid_time).split(' ')[1].slice(0,-3)}</text>`).join('')}</svg>`;
 return `<section class="card chart-card"><div class="card-heading"><div><h2>Мощность</h2></div><div class="segmented" aria-label="Турбины на графике">${[['both','Обе'],['1','Турбина 1'],['2','Турбина 2']].filter(([id])=>id==='both'||run.turbines.includes(id)).map(([id,l])=>`<button data-chart-turbine="${id}" class="${state.chartTurbine===id?'active':''}" aria-pressed="${state.chartTurbine===id}">${l}</button>`).join('')}</div></div><div class="chart-subhead"><span>Нормализованная мощность</span><span>Asia/Almaty · ${run.horizon} ч</span></div><div class="chart-container" id="chart-container">${svg}<div class="chart-tooltip" id="chart-tooltip"></div></div><div class="chart-legend">${ids.map(id=>`<span><i class="legend-line ${id==='2'?'second':''}"></i>Турбина ${id} · среднее</span>`).join('')}<span><i class="legend-band"></i>Диапазон прогноза</span></div><div class="chart-bottom"><button class="text-button" data-action="show-hourly">Открыть таблицу ${icon('arrow')}</button></div></section>`;
}
function localTrust(){
 return `<aside class="card trust-card"><h2>Что важно знать</h2><p>Проверьте ограничения перед принятием решения.</p><div class="trust-row">${icon('shield')}<div><b>${qualityText(run.quality)}</b><small>Статус демонстрационного результата</small></div></div><div class="trust-row">${icon('cloud')}<div><b>Погодный источник не подключён</b><small>Сейчас показан пример, не рабочий прогноз.</small></div></div><div class="trust-row">${icon('spark')}<div><b>Объяснение пока недоступно</b><small>Это не мешает посмотреть числа.</small></div></div><button class="text-button" data-action="passport">Сведения о прогнозе ${icon('arrow')}</button></aside>`;
}
function trust(){
 if(!run.remote)return localTrust();
 const weather=run.weatherRuns?.[0],fixture=run.mode==='fixture';
 return `<aside class="card trust-card"><h2>Что важно знать</h2><p>Проверьте ограничения перед принятием решения.</p><div class="trust-row">${icon('shield')}<div><b>${qualityText(run.quality)}</b><small>Статус результата backend</small></div></div><div class="trust-row">${icon('cloud')}<div><b>${esc(weather?.provider||'Источник не предоставлен')}</b><small>${weather?`Доступен с ${csvTime(weather.effective_available_at)}`:'Паспорт погоды отсутствует'}</small></div></div><div class="trust-row">${icon('spark')}<div><b>${run.explanation==='unavailable'?'Объяснение недоступно':'Объяснение: '+esc(run.explanation)}</b><small>${fixture?'Синтетический режим разработки':'Числовой прогноз доступен независимо от текста'}</small></div></div><button class="text-button" data-action="passport">Сведения о прогнозе ${icon('arrow')}</button></aside>`;
}
function forecastPage(){
 return `${config()}${currentNotice()?`<div class="section-gap">${currentNotice()}</div>`:''}
 ${hasResult(run)?`<div class="result-heading"><h2>Выпуск ${compactTime(run.origin)}</h2>${button('Аналитика','show-analysis','primary','chart')}</div>${chart()}${detailNote('forecast-context','Сведения о прогнозе',trust())}`:
 `<section class="card section-gap">${empty(run.stage==='initial'?'Прогноз ещё не создан':run.stage==='failed'||run.stage==='python_unavailable'?'Результат не получен':run.stage==='cancelled'?'Расчёт остановлен':'Результат ещё не готов','Готовые выпуски доступны в аналитике.','chart',button('Открыть аналитику','show-analysis','ghost','clock'))}</section>`}
 ${stateSelector()}`;
}
function forecastTable(){
 if(!run.points.length)return `<section class="card">${empty('Нет почасовых значений','Выберите другой выпуск или дождитесь результата расчёта.','clock')}</section>`;
 const rows=run.points.slice(state.tablePage*12,(state.tablePage+1)*12),total=Math.ceil(run.points.length/12),details=state.quantileDetails;
 const headers=details?['Дата и время','Конец часа','Турбина','Средняя мощность','Нижняя граница · q10','Медиана · q50','Верхняя граница · q90']:['Дата и время','Турбина','Средняя мощность','Диапазон прогноза'];
 let lastDay='';
 const tableRows=rows.map(p=>{const day=csvTime(p.valid_time).split(' ')[0],heading=day!==lastDay?`<tr class="day-summary"><th scope="rowgroup" colspan="${headers.length}">${day.split('-').reverse().join('.')}</th></tr>`:'';lastDay=day;return heading+`<tr><td>${csvTime(p.valid_time)}</td>${details?`<td>${csvTime(p.interval_end)}</td>`:''}<td>Турбина ${p.turbine_id}</td><td class="yellow">${num(p.power_mean)}</td>${details?`<td>${num(p.q10)}</td><td>${num(p.q50)}</td><td>${num(p.q90)}</td>`:`<td>${num(p.q10)} — ${num(p.q90)}</td>`}</tr>`;}).join('');
 return `<section class="card analytics-table"><div class="table-actions"><h2>Почасовой прогноз</h2><div class="heading-actions">${button('Скачать CSV','export','primary','download')}${button('Новый прогноз','new-preview','ghost','repeat')}<button class="button ghost" data-action="toggle-quantiles" aria-label="Подробные границы диапазона" aria-pressed="${details}">${details?'Скрыть границы':'Границы'}</button></div></div>
 <div class="table-wrap" tabindex="0" role="region" aria-label="Таблица почасового прогноза"><table><caption class="sr-only">Почасовой прогноз выбранного выпуска. Нормализованная мощность, не кВт.</caption><thead><tr>${headers.map(h=>`<th scope="col">${h}</th>`).join('')}</tr></thead><tbody>${tableRows}</tbody></table></div>
 <div class="table-foot"><span>${state.tablePage*12+1}–${Math.min((state.tablePage+1)*12,run.points.length)} из ${run.points.length}</span><div>${button('Назад','prev-page','ghost','',`aria-label="Предыдущая страница" ${state.tablePage===0?'disabled':''}`)} <span>${state.tablePage+1} / ${total}</span> ${button('Далее','next-page','ghost','',`aria-label="Следующая страница" ${state.tablePage===total-1?'disabled':''}`)}</div></div>${detailNote('table-guide','Как читать данные','<p>Значения нормализованы — это не кВт. Для пересчёта используйте «План энергии».</p><p>Дата и время — начало часа. Конец периода не включён. Диапазон q10–q90 показывает неопределённость, а не гарантированные границы. Ноль мощности — допустимое значение.</p>')}</section>`;
}
function analyticsKpis(selected){
 const s=powerOverview(selected.points,selected.turbines);
 const values=key=>s.turbines.map(t=>`<b><small>Т${esc(t.id)}</small> ${num(t[key])}</b>`).join('');
 return `<p class="analytics-unit">Нормализованная мощность · по турбинам</p><div class="analytics-kpis" aria-label="Показатели выбранного выпуска"><article class="card analytics-kpi"><span class="kpi-icon">${icon('file')}</span><div><span>Записей</span><strong>${s.records}</strong></div></article>${[['mean','Средняя','chart'],['min','Минимум','wind'],['max','Максимум','bolt']].map(([key,label,symbol])=>`<article class="card analytics-kpi"><span class="kpi-icon">${icon(symbol)}</span><div><span>${label}</span><div class="kpi-values">${values(key)}</div></div></article>`).join('')}</div>${s.unavailable?notice('Часть значений недоступна',`Исключено из статистики: ${s.unavailable}.`,'warn'):''}`;
}
function stat(label,value,unit,note,symbol='bolt',featured=false){return `<article class="card stat ${featured?'featured':''}"><div class="label">${label}${icon(symbol)}</div><div class="value">${value}${unit?`<small>${unit}</small>`:''}</div><div class="footnote">${note}</div></article>`;}
function energyForm(){const f=state.energyInput;return `<section class="card pad"><div class="card-heading"><div><h2>Параметры сценария</h2></div>${icon('bolt')}</div><form id="energy-form" class="energy-form"><div class="form-grid">${run.turbines.map(t=>field(`Мощность турбины ${t} по паспорту, кВт`,`capacity-${t}`,`<input type="number" id="capacity-${t}" min="0.01" step="any" placeholder="Введите мощность" value="${esc(f['p'+t])}" required>`)).join('')}${field('План станции за час, кВт·ч','energy-plan',`<input type="number" id="energy-plan" min="0" step="any" placeholder="Введите план" value="${esc(f.plan)}" required>`)}</div><label class="check-label"><input type="checkbox" id="normalize-confirm" ${f.confirmed?'checked':''} required><span>Принимаю допущение: нормализация по паспортной мощности (не подтверждено).</span></label><button id="energy-submit" type="submit" class="button primary">${icon('chart')}Рассчитать сценарий</button></form>${detailNote('energy-method','Как считаем','<p>Средняя мощность × 1 час = энергия. Дефицит = max(план − энергия, 0) по каждому часу станции. Это не ожидаемый вероятностный дефицит.</p>')}</section>`;}
function energyResults(){const e=state.energy;if(!e)return `<aside class="card insight"><h2>Баланс энергии</h2><p>Введите мощности и план.</p><button class="button" data-action="energy-help">Какие данные нужны ${icon('arrow')}</button>${icon('bolt')}</aside>`;
 return `<section class="card pad"><div class="card-heading"><h2>Сценарий, не факт</h2>${pill('Допущения','warn')}</div><p id="energy-stale" class="notice-text" role="status" ${state.energyDirty?'':'hidden'}>Параметры изменены. Пересчитайте сценарий.</p>${kv([['Выработка по среднему',`${num(e.total.energy,1)} кВт·ч`],['План за период',`${num(e.total.plan,1)} кВт·ч`],['Расчётная докупка / дефицит',`<span class="delta">${num(e.total.deficit,1)} кВт·ч</span>`],['Избыток',`${num(e.total.surplus,1)} кВт·ч`],['Полных часов',String(e.completeHours)],['Неполных часов',String(e.missingHours)],['Фактически куплено','Нет данных'],['Физические потери','Не определяются по CSV']])}${detailNote('energy-limits','Ограничения','<p>Для финансовых потерь нужны тарифы и правила небаланса. Дефицит по плану не означает физические потери.</p>')}${button('CSV сценария','export-energy','ghost','download',state.energyDirty?'disabled':'')}</section>`;
}
function reportDetails(selected){
 if(!selected)return `<section class="card analysis-panel">${empty('Выберите выпуск','Нет нужного? Измените даты поиска.','clock')}</section>`;
 const first=selected.points[0],last=selected.points.at(-1);
 const period=first&&last?`${compactTime(first.valid_time)} — ${compactTime(last.interval_end)}`:'Нет почасовых значений';
 return `<div class="analysis-panel"><div class="report-context-strip"><div><h2 class="sr-only" id="selected-run-title" tabindex="-1">Выпуск: ${friendlyTime(selected.origin)}</h2><p>Прогноз: ${period} · Алматы</p></div>${stagePill(selected.stage)}</div>
 ${!hasResult(selected)||!selected.points.length?`<section class="card section-gap">${empty('Для этого выпуска нет готовых значений',STATE_LABELS[selected.stage]+'. Выберите другой выпуск или создайте новый прогноз.','info',button('Новый прогноз','new-preview','primary','play'))}</section>`:
 `<div class="analysis-tabs" role="group" aria-label="Представление анализа">${[['hourly','По часам','clock'],['overview','График','chart'],['energy','План энергии','bolt']].map(([id,label,symbol])=>`<button class="${state.reportTab===id?'active':''}" data-report-tab="${id}" aria-pressed="${state.reportTab===id}">${icon(symbol)}${label}</button>`).join('')}</div>
 ${selected.quality==='degraded'?notice('Есть замечания','Использован запасной источник.','warn'):''}
 ${state.reportTab==='overview'?`${chart()}${detailNote('report-context','Сведения о прогнозе',trust())}`:
 state.reportTab==='hourly'?analyticsKpis(selected)+forecastTable():
 `<div class="selection-hint">${icon('info')}<p>Сценарий, не фактические покупки или потери.</p></div><div class="equal-grid">${energyForm()}${energyResults()}</div>${state.energy?energyHourly():''}`}`}</div>`;
}
function energyHourly(){return `<section class="card section-gap"><div class="table-head"><div><h2>Баланс по часам · сценарий</h2></div>${pill('Первые 8 часов','neutral')}</div><div class="table-wrap" tabindex="0" role="region" aria-label="Сценарий энергии по часам"><table><thead><tr><th>Дата и время</th><th>Мощность, кВт</th><th>Энергия, кВт·ч</th><th>План, кВт·ч</th><th>Докупка*, кВт·ч</th><th>Избыток, кВт·ч</th></tr></thead><tbody>${state.energy.rows.slice(0,8).map(r=>`<tr><td>${csvTime(r.time)}</td>${r.complete?`<td>${num(r.power,1)}</td><td>${num(r.energy,1)}</td><td>${num(r.plan,1)}</td><td class="delta">${num(r.deficit,1)}</td><td>${num(r.surplus,1)}</td>`:'<td colspan="5">Неполный час — не считается</td>'}</tr>`).join('')}</tbody></table></div><div class="table-foot">* Расчётная потребность в докупке, не сведения о совершённой покупке.</div></section>`;}
function reportsPage(){
 const f=state.filters,rows=filterHistory(history,f),selected=visibleSelection(rows,state.reportRunId);
 if(selected&&run!==selected){run=selected;state.chartTurbine='both';state.tablePage=0;state.energy=null;state.energyInput={p1:'',p2:'',plan:'',confirmed:false};}
 // Render never substitutes another origin when filters exclude the current selection.
 return `<form class="card filters reports-toolbar" id="history-form" aria-label="Поиск выпусков">
 ${field('Дата выпуска: с','history-from',`<input type="date" id="history-from" value="${f.from}">`)}
 ${field('Дата выпуска: по','history-to',`<input type="date" id="history-to" value="${f.to}">`)}
 ${field('Турбина','history-turbine',`<select id="history-turbine">${[['all','Все турбины'],['1','Турбина 1'],['2','Турбина 2']].map(([v,l])=>`<option value="${v}" ${f.turbine===v?'selected':''}>${l}</option>`).join('')}</select>`)}
 <button id="history-submit" type="submit" class="button primary">${icon('filter')}Найти</button>
 <details class="advanced filter-advanced" id="history-extra"><summary>Другие фильтры</summary><p class="filter-hint">Даты «с — по» включены и относятся к <b>выпуску</b>, не к прогнозируемому дню. Время Алматы.</p><div class="form-grid">
 ${field('Статус','history-status',`<select id="history-status">${[['all','Все статусы'],['queued','В очереди'],['running','Выполняется'],['completed','Готов'],['failed','Не удалось рассчитать'],['cancelled','Отменён']].map(([v,l])=>`<option value="${v}" ${f.status===v?'selected':''}>${l}</option>`).join('')}</select>`)}
 ${field('Режим данных','history-mode',`<select id="history-mode"><option value="all" ${f.mode==='all'?'selected':''}>Все режимы</option><option value="fixture" ${f.mode==='fixture'?'selected':''}>Backend fixture</option><option value="synthetic" ${f.mode==='synthetic'?'selected':''}>Локальная иллюстрация</option></select>`)}</div></details></form>
 <section class="card report-picker">${field('Выпуск','report-run',`<select id="report-run" ${!rows.length?'disabled':''}><option value="" ${!selected?'selected':''} disabled>${rows.length?'Выберите выпуск':'Выпуски не найдены'}</option>${rows.map(r=>`<option value="${esc(r.key)}" ${selected?.key===r.key?'selected':''}>${compactTime(r.origin)} · ${r.horizon} ч · ${r.turbines.length===2?'Т1 + Т2':'Т'+r.turbines[0]} · ${STATE_LABELS[r.stage]||esc(r.stage)}</option>`).join('')}</select>`)}<button class="text-button" data-action="sort-history">${f.sort==='desc'?'Сначала новые':'Сначала старые'} ${icon('repeat')}</button>${!rows.length?button('Сбросить фильтры','reset-history','ghost','repeat'):''}</section>
 ${reportDetails(selected)}`;
}
function localReplayPage(){const b=state.replay,d=state.replayDraft;const count=s=>b?b.children.filter(r=>statusOf(r.stage)===s).length:0;return `${heading('Прогнозы за период','Воспроизведите выпуски с тем, что было известно тогда.')}<form id="replay-form" class="card filters">${field('Первая дата выпуска','replay-from',`<input type="date" id="replay-from" min="2026-01-01" max="2026-02-28" value="${d.from}" required>`)}${field('Последняя дата выпуска','replay-to',`<input type="date" id="replay-to" min="2026-01-01" max="2026-02-28" value="${d.to}" required>`)}${field('Время выпуска · Asia/Almaty','replay-time','<input type="time" id="replay-time" value="23:00" step="3600" required>')}${field('Горизонт','replay-horizon',`<select id="replay-horizon"><option value="48" ${d.horizon===48?'selected':''}>48 часов</option><option value="24" ${d.horizon===24?'selected':''}>24 часа</option></select>`)}<button id="replay-submit" type="submit" class="button primary">${icon('play')}Создать пакет · пример</button></form><p class="filter-hint">Один выпуск в сутки · обе турбины · текущий режим: синтетическая иллюстрация.</p><div class="stat-grid">${stat('Всего заданий',b?b.children.length:'—','','Пакет исторических выпусков','repeat')}${stat('Завершено',b?count('completed'):'—','','Результаты можно открыть','check',true)}${stat('С ошибкой',b?count('failed'):'—','','Не удаляет успешные результаты','warning')}${stat('Отменено',b?count('cancelled'):'—','','Отдельный статус задания','close')}</div><section class="card">${b?`<div class="table-head"><div><h2>Дочерние задания</h2><p>${b.children.length} выпусков · ${STATE_LABELS[b.status]||b.status} · пример</p></div>${count('completed')?button(count('completed')===b.children.length?'CSV пакета':'Частичный CSV','export-replay','','download'):pill('Результатов пока нет')}</div><div class="table-wrap" tabindex="0" role="region" aria-label="Дочерние задания replay"><table><thead><tr><th>Момент выпуска</th><th>Турбины</th><th>Горизонт</th><th>Статус</th><th>Результат</th></tr></thead><tbody>${b.children.map(r=>`<tr><td>${csvTime(r.origin)}</td><td>01 + 02</td><td>${r.horizon} ч</td><td>${stagePill(r.stage)}</td><td>${hasResult(r)?`<button class="text-button" data-replay-run="${r.key}">Открыть ${icon('arrow')}</button>`:'—'}</td></tr>`).join('')}</tbody></table></div>`:empty('Восстановить февраль по шагам','Выберите даты выпуска и создайте макет пакета. Реальный replay выполнит Go после подключения согласованного контракта.','repeat')}</section>${b?`<div class="state-strip">${icon('grid')}<div><b>Состояние макета пакета</b><p>Явное переключение, не симуляция работы агента.</p></div><select id="replay-state" aria-label="Состояние replay">${[['queued','В очереди'],['partial','Частичный сбой'],['completed','Все завершены'],['cancelled','Все отменены']].map(([v,l])=>`<option value="${v}" ${b.view===v?'selected':''}>${l}</option>`).join('')}</select></div>`:''}<p class="data-meta">В феврале 2026 — 672 целевых часа на турбину. У 48-часовых выпусков есть перекрытия: больше строк не означает ошибку. Часы за пределами февраля не входят в оценку февраля.</p>`;}
function localQualityPage(){return `${heading('Качество модели','')}${notice('Отчёт оценки ещё не подключён','Фактических февральских значений в предоставленных CSV нет. Февральскую точность и линию «факт» не показываем.','warn')}<section class="card filters"><div class="field"><label for="evaluation-period">Период проверки</label><select id="evaluation-period" disabled><option>Нет опубликованных отчётов</option></select></div><div class="field"><label for="evaluation-model">Модель / baseline</label><select id="evaluation-model" disabled><option>Отчёты ещё не подключены</option></select></div>${pill('Нет оценки точности','neutral')}</section><div class="stat-grid">${[['MAE','Средняя абсолютная ошибка'],['RMSE','Сильнее учитывает большие ошибки'],['Bias','Систематическое смещение'],['Coverage','Покрытие q10–q90']].map(([label,detail])=>`<article class="card empty-metric"><h3>${label}</h3><strong>—</strong><span>${detail}</span></article>`).join('')}</div><div class="equal-grid"><section class="card">${empty('Нет данных для сравнения','Здесь появится модель против baseline, ширина интервала и метрики по каждой турбине и горизонту. Отсутствующий отчёт — не нулевая ошибка.','chart')}</section><section class="card pad"><h2>Что должно быть в отчёте</h2>${kv([['Источник метрик','Не предоставлен'],['data_mode','Не предоставлен'],['evaluation_scope','Не предоставлен'],['Ширина интервала','—'],['Модель / baseline','—']])}<p class="notice-text">end_to_end оценивает весь прогноз с погодными входами. power_conversion_only — только преобразование ветра в мощность. Эти результаты нельзя подменять друг другом.</p></section></div>`;}
function localAgentPage(){return `${heading('Источники и работа системы','Каждое решение должно оставлять проверяемый след.',button('Паспорт','passport','','file'))}<div class="equal-grid"><section class="card pad"><div class="card-heading"><div><h2>Лента событий</h2><p>${run.key} · подключение SSE отсутствует</p></div>${pill('Не подключено')}</div><div class="event-empty">${icon('spark')}<p>События пока не поступают.</p></div><div class="timeline">${['Погода','Подготовка','Модель','Проверка','Результат'].map((s,i)=>`<div class="timeline-step"><b>0${i+1} / ${s}</b><small>Ожидаем событие</small></div>`).join('')}</div>${detailNote('event-details','О событиях','<p>Показана схема, не журнал выполнения. При потере SSE используется polling. Закрытие вкладки не отменяет задание.</p>')}</section><section class="card pad"><div class="card-heading"><h2>Паспорт погодного входа</h2>${icon('cloud')}</div>${kv([['Планируемый источник','GFS'],['initialization_time','Не предоставлено'],['effective_available_at','Не предоставлено'],['availability_basis','Не предоставлено'],['model_version','Не подключена'],['feature_version','Не предоставлено']])}<p class="notice-text">Без времени доступности погодного запуска нельзя подтвердить, что он был известен на исторический origin.</p></section></div><div class="equal-grid section-gap"><section class="card pad"><div class="card-heading"><h2>Объяснение прогноза</h2>${pill('Нет объяснения')}</div><p class="instructions">Объяснение недоступно. Числовой прогноз от этого не зависит.</p></section><section class="card pad"><div class="card-heading"><h2>Вклад признаков · SHAP</h2>${pill('Нет артефакта')}</div><p class="instructions">Нет данных о влиянии признаков.</p></section></div>`;}
const rawSamples=[['2023-03-11 0:00:00','1',6.73,.39,15.38],['2023-03-11 0:00:00','2',6.62,.37,15.52],['2023-03-11 0:10:00','1',6.75,.39,15.26],['2023-03-11 0:10:00','2',6.7,.39,15.38],['2023-03-11 0:20:00','1',6.87,.41,15.29],['2023-03-11 0:20:00','2',7.14,.44,15.43]];
function localDataPage(){return `${heading('Исходные данные','Понимайте, на чём строится прогноз.')}<div class="equal-grid">${[{id:1,count:142360,missing:9992},{id:2,count:149499,missing:2853}].map(d=>`<section class="card pad"><div class="card-heading"><h2>ВЭУ 0${d.id}</h2>${pill('Есть пропуски','warn','warning')}</div><p class="muted small">11.03.2023 — 31.01.2026 · шаг 10 минут</p><div class="stat"><div class="value">${num(d.count/152352*100,2)}<small>% покрытия сетки</small></div></div><div class="progress-track"><span style="width:${d.count/152352*100}%"></span></div>${kv([['Строк в CSV',num(d.count,0)],['Пропущено интервалов',num(d.missing,0)],['Дубликаты времени','0'],['Номинальная мощность','Неизвестна']])}</section>`).join('')}</div><section class="card section-gap"><div class="table-head"><div><h2>Первые измерения CSV</h2><p>Измерения CSV · не прогноз</p></div>${pill('10 минут')}</div><div class="table-wrap" tabindex="0" role="region" aria-label="Образец исходных CSV"><table><thead><tr><th>Статистическое время</th><th>Турбина</th><th>Ветер, м/с</th><th>Нормализованная мощность</th><th>Температура, °C</th></tr></thead><tbody>${rawSamples.map(r=>`<tr><td>${r[0]}</td><td>ВЭУ 0${r[1]}</td><td>${num(r[2],2)}</td><td>${num(r[3],2)}</td><td>${num(r[4],2)}</td></tr>`).join('')}</tbody></table></div></section><div class="card pad section-gap"><h2>Границы данных</h2><div class="source-line"><div><b>Февраль 2026 не содержится в файлах</b></div>${icon('info')}</div><div class="source-line"><div><b>Часовой пояс SCADA неизвестен</b></div>${icon('clock')}</div><div class="source-line"><div><b>Пропуск ≠ нулевая выработка</b></div>${icon('shield')}</div></div>`;}

function replayPage(){
 if(!backend.capabilities.replay)return localReplayPage();
 const b=state.replay,d=state.replayDraft;
 const counters=b?.counters||{total:b?.children?.length||0,queued:0,running:0,completed:0,failed:0,cancelled:0};
 const terminal=b&&['completed','failed','cancelled'].includes(b.status),busy=b&&['submitting','queued','running'].includes(b.status);
 const rows=b?.children||[];
 return `${heading('Прогнозы за период','Backend создаёт отдельный исторический выпуск для каждого origin.')}
 <form id="replay-form" class="card filters">
 ${field('Первая дата выпуска','replay-from',`<input type="date" id="replay-from" min="2026-01-01" max="2026-02-28" value="${d.from}" required>`)}
 ${field('Последняя дата выпуска','replay-to',`<input type="date" id="replay-to" min="2026-01-01" max="2026-02-28" value="${d.to}" required>`)}
 ${field('Время выпуска · Asia/Almaty','replay-time',`<input type="time" id="replay-time" value="${d.time}" step="3600" required>`)}
 ${field('Горизонт','replay-horizon',`<select id="replay-horizon"><option value="48" ${d.horizon===48?'selected':''}>48 часов</option><option value="24" ${d.horizon===24?'selected':''}>24 часа</option></select>`)}
 <button id="replay-submit" type="submit" class="button primary" ${busy?'disabled':''}>${icon('play')}${busy?'Пакет выполняется':'Создать пакет'}</button></form>
 <p class="filter-hint">Один выпуск в сутки · обе турбины · синтетический режим backend fixture.</p>
 ${b?.error?notice('Не удалось создать пакет',esc(b.error),'error'):''}
 <div class="stat-grid">${stat('Всего заданий',b?counters.total:'—','','Пакет исторических выпусков','repeat')}${stat('Завершено',b?counters.completed:'—','','Результаты можно открыть','check',true)}${stat('С ошибкой',b?counters.failed:'—','','Успешные результаты сохраняются','warning')}${stat('Отменено',b?counters.cancelled:'—','','Отдельный статус задания','close')}</div>
 <section class="card">${b?`<div class="table-head"><div><h2>Дочерние задания</h2><p>${esc(b.id||'Ожидание идентификатора')} · ${STATE_LABELS[b.status]||esc(b.status)}</p></div>${terminal&&counters.completed?button(counters.completed===counters.total?'CSV пакета':'Частичный CSV','export-replay','','download'):stagePill(b.status)}</div>${rows.length?`<div class="table-wrap" tabindex="0" role="region" aria-label="Дочерние задания replay"><table><thead><tr><th>Момент выпуска</th><th>Турбины</th><th>Горизонт</th><th>Статус</th><th>Результат</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${csvTime(r.origin)}</td><td>${r.turbines.map(id=>'Т'+esc(id)).join(' + ')}</td><td>${r.horizon} ч</td><td>${stagePill(r.stage)}</td><td>${hasResult(r)?`<button class="text-button" data-replay-run="${esc(r.key)}">Открыть ${icon('arrow')}</button>`:'—'}</td></tr>`).join('')}</tbody></table></div>`:empty(busy?'Backend формирует задания':'Нет дочерних заданий','Список обновится после принятия пакета.','clock')}`:empty('Восстановить период по шагам','Выберите даты выпуска и создайте пакет в Go backend.','repeat')}</section>
 <p class="data-meta">Пересекающиеся valid_time относятся к разным выпускам и не объединяются. Частичный CSV явно помечается backend.</p>`;
}

function qualityPage(){
 if(!backend.capabilities.evaluations)return localQualityPage();
 const reports=state.evaluations,report=reports.find(item=>item.evaluation_id===state.evaluationId)||reports[0];
 if(!report)return `${heading('Качество модели','')}${empty('Нет отчётов оценки','Backend вернул пустой список. Отсутствие отчёта не означает нулевую ошибку.','shield')}`;
 const metric=(key,digits=3)=>report.metrics.map(item=>`<b><small>Т${item.turbine_id}</small> ${num(item[key],digits)}</b>`).join('');
 const cards=[['mae','MAE','Средняя абсолютная ошибка',3],['rmse','RMSE','Сильнее учитывает большие ошибки',3],['bias','Bias','Систематическое смещение',3],['coverage_q10_q90','Coverage','Покрытие q10–q90',2]];
 return `${heading('Качество модели','')}${notice('Синтетическая оценка backend','Режим fixture демонстрирует формат отчёта; реальная проверка модели не выполнялась.','warn')}
 <section class="card filters">${field('Отчёт','evaluation-report',`<select id="evaluation-report">${reports.map(item=>`<option value="${esc(item.evaluation_id)}" ${item.evaluation_id===report.evaluation_id?'selected':''}>${esc(item.evaluation_id)} · ${esc(item.status)}</option>`).join('')}</select>`)}${field('Модель / baseline','evaluation-model',`<select id="evaluation-model" disabled><option>${esc(report.model_version)} / ${esc(report.baseline_name)}</option></select>`)}${pill(report.status==='available'?'Доступен':'Недоступен',report.status==='available'?'ok':'neutral')}</section>
 <div class="stat-grid">${cards.map(([key,label,detail,digits])=>`<article class="card analytics-kpi"><span class="kpi-icon">${icon('chart')}</span><div><span>${label}</span><div class="kpi-values">${metric(key,digits)}</div><small>${detail}</small></div></article>`).join('')}</div>
 <div class="equal-grid"><section class="card analytics-table"><div class="table-head"><div><h2>Метрики по турбинам</h2><p>Нормализованная мощность</p></div>${pill(report.data_mode==='fixture'?'Fixture':'Real',report.data_mode==='fixture'?'warn':'ok')}</div><div class="table-wrap"><table><thead><tr><th>Турбина</th><th>Горизонт</th><th>MAE</th><th>RMSE</th><th>Bias</th><th>q10–q90</th><th>Ширина интервала</th></tr></thead><tbody>${report.metrics.map(item=>`<tr><td>Т${item.turbine_id}</td><td>${item.lead_from}–${item.lead_to} ч</td><td>${num(item.mae)}</td><td>${num(item.rmse)}</td><td>${num(item.bias)}</td><td>${num(item.coverage_q10_q90)}</td><td>${num(item.mean_interval_width)}</td></tr>`).join('')}</tbody></table></div></section><section class="card pad"><h2>Паспорт оценки</h2>${kv([['Период',`${csvTime(report.period_start)} — ${csvTime(report.period_end)}`],['Объём',report.n_observations==null?'Не предоставлен':num(report.n_observations,0)],['evaluation_scope',esc(report.evaluation_scope)],['Обучение по',csvTime(report.training_data_available_through)],['Единица',esc(report.target_unit)]])}<p class="notice-text">${report.notes.map(esc).join('<br>')||'Примечаний нет.'}</p></section></div>`;
}

function agentPage(){
 if(!run.remote)return localAgentPage();
 const extra=runExtras.get(run.key);
 if(!extra||extra.loading)return `${heading('Источники и работа системы','Каждое решение должно оставлять проверяемый след.',button('Паспорт','passport','','file'))}<section class="card">${empty('Загружаем сведения backend','События, погода и объяснение запрашиваются для выбранного выпуска.','spark')}</section>`;
 const weather=extra.weather,provenance=weather?.weather_runs?.[0],explanation=extra.explanation,events=extra.events||[];
 return `${heading('Источники и работа системы','Каждое решение оставляет проверяемый след.',button('Паспорт','passport','','file'))}
 ${extra.error?notice('Часть сведений недоступна',esc(extra.error),'warn'):''}<div class="equal-grid"><section class="card pad"><div class="card-heading"><div><h2>Лента событий</h2><p>${esc(run.key)} · ${events.length} событий</p></div>${pill(backend.capabilities.sse?'SSE + polling':'Polling',backend.capabilities.sse?'ok':'neutral')}</div>${events.length?`<div class="timeline">${events.map(event=>`<div class="timeline-step"><b>${String(event.event_id).padStart(2,'0')} / ${esc(event.node)}</b><small>${csvTime(event.recorded_at)} · ${esc(event.message)}</small></div>`).join('')}</div>`:`<div class="event-empty">${icon('spark')}<p>События не найдены.</p></div>`}${detailNote('event-details','О событиях','<p>Интерфейс получает live-события через SSE и переключается на polling при разрыве соединения.</p>')}</section>
 <section class="card pad"><div class="card-heading"><h2>Паспорт погодного входа</h2>${icon('cloud')}</div>${kv([['Статус',esc(weather?.status||'Недоступно')],['Источник',esc(provenance?.provider||'Не предоставлен')],['initialization_time',provenance?csvTime(provenance.initialization_time):'Не предоставлено'],['effective_available_at',provenance?csvTime(provenance.effective_available_at):'Не предоставлено'],['availability_basis',esc(provenance?.availability_basis||'Не предоставлено')],['model_version',esc(run.model||'Не предоставлена')],['feature_version',esc(run.featureVersion||'Не предоставлено')]])}<p class="notice-text">${weather?.data_mode==='fixture'?'Синтетическая погода backend — не наблюдения GFS.':'Источник и время доступности получены от backend.'}</p></section></div>
 <div class="equal-grid section-gap"><section class="card pad"><div class="card-heading"><h2>Объяснение прогноза</h2>${pill(explanation?.status||'Недоступно',explanation?.status==='unavailable'?'neutral':'ok')}</div><p class="instructions">${esc(explanation?.text||run.explanationText||'Объяснение недоступно. Числовой прогноз от этого не зависит.')}</p></section><section class="card pad"><div class="card-heading"><h2>Вклад признаков · SHAP</h2>${pill(explanation?.shap_status||'Недоступно')}</div>${explanation?.shap_items?.length?`<p class="instructions">Получено объектов: ${explanation.shap_items.length}.</p>`:'<p class="instructions">Backend не предоставил SHAP-артефакты.</p>'}</section></div>`;
}

function dataPage(){
 if(!backend.capabilities.data_quality)return localDataPage();
 const report=state.dataQuality;
 if(!report)return `${heading('Исходные данные','Понимайте, на чём строится прогноз.')}<section class="card">${empty('Аудит данных недоступен','Backend не вернул отчёт качества данных. Неизвестные значения не считаются нулевыми.','database')}</section>`;
 return `${heading('Исходные данные','Аудит качества получен из канонического API.')}${report.data_mode==='fixture'?notice('Синтетический аудит backend','Показанные диапазоны и счётчики демонстрируют контракт, а не проверку исходной SCADA.','warn'):''}<div class="equal-grid">${report.turbines.map(item=>`<section class="card pad"><div class="card-heading"><h2>ВЭУ 0${item.turbine_id}</h2>${pill(item.missing_hour_count===0?'Пропусков нет':'Есть пропуски',item.missing_hour_count===0?'ok':'warn',item.missing_hour_count===0?'check':'warning')}</div><p class="muted small">${item.range_start?csvTime(item.range_start):'Начало неизвестно'} — ${item.range_end?csvTime(item.range_end):'конец неизвестен'}</p>${kv([['Строк',item.row_count==null?'Неизвестно':num(item.row_count,0)],['Полных часов',item.complete_hour_count==null?'Неизвестно':num(item.complete_hour_count,0)],['Пропущено часов',item.missing_hour_count==null?'Неизвестно':num(item.missing_hour_count,0)]])}<p class="notice-text">${item.warnings.map(esc).join('<br>')||'Предупреждений нет.'}</p></section>`).join('')}</div><section class="card pad section-gap"><h2>Паспорт отчёта</h2>${kv([['Статус',esc(report.status)],['Сформирован',report.generated_at?csvTime(report.generated_at):'Не предоставлено'],['Источник',esc(report.source_reference||'Не предоставлен')],['Режим данных',esc(report.data_mode)]])}<p class="notice-text">Пропуск не равен нулевой выработке. Неизвестные счётчики отображаются как «Неизвестно».</p></section>`;
}
const pages={home:homePage,forecast:forecastPage,reports:reportsPage,replay:replayPage,quality:qualityPage,agent:agentPage,data:dataPage};
function render(){
 const active=document.activeElement;
 const focusId=active?.id;
 const focusAttr=['data-horizon','data-chart-turbine','data-report-tab','data-action','data-open-run'].find(a=>active?.hasAttribute?.(a));
 const focusValue=focusAttr?active.getAttribute(focusAttr):null;
 const openDetails=[...document.querySelectorAll('main details[open][id]')].map(d=>d.id);
 $('#main').innerHTML=pages[state.page]();
 const pageTitles={forecast:'Прогноз',reports:'Аналитика',replay:'Прогнозы за период',quality:'Качество модели',agent:'Источники и агент',data:'Исходные данные'};
 $('.header-context').innerHTML=state.page==='home'?'':`<h1 id="page-title" tabindex="-1">${pageTitles[state.page]}</h1>`;
 document.body.dataset.page=state.page;syncSidebar();
 document.querySelectorAll('.sidebar-nav [data-page]').forEach(a=>{a.classList.toggle('active',a.dataset.page===state.page);if(a.dataset.page===state.page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
 document.body.classList.toggle('large-text',state.largeText);
 document.querySelectorAll('[data-action="reading-size"]').forEach(el=>el.setAttribute('aria-pressed',String(state.largeText)));
 for(const id of openDetails){const detail=document.getElementById(id);if(detail)detail.open=true;}
 const nextFocus=focusId?document.getElementById(focusId):focusAttr?[...document.querySelectorAll('['+focusAttr+']')].find(el=>el.getAttribute(focusAttr)===focusValue):null;
 if(nextFocus&&!nextFocus.disabled)nextFocus.focus({preventScroll:true});
 decorate();bindChart();
}
function navigate(){
 navigationVersion++;
 let page=location.hash.slice(1);
 if(page==='overview')page='forecast';
 if(page==='analytics'||page==='history'){page='reports';window.history.replaceState(null,'','#reports');}
 state.page=pages[page]?page:'home';
 closeNavigation(false);closeModal();render();window.scrollTo({top:0,behavior:'instant'});
 if(state.page==='agent')void loadRunExtras(run);
 if(navigationFocusRequested){$('#page-title')?.focus({preventScroll:true});navigationFocusRequested=false;}
}
async function loadRun(next,destination='forecast'){
 if(!next)return;
 const sequence=++loadRunSequence,version=navigationVersion;
 if(next.remote&&hasResult(next)&&!next.points.length){
  try{
   const result=await api.result(next.key);
   if(sequence!==loadRunSequence||version!==navigationVersion)return;
   attachResult(next,result);
  }catch(error){if(sequence===loadRunSequence&&version===navigationVersion){navigationFocusRequested=false;toast(error.message);}return;}
 }
 run=next;state.chartTurbine='both';state.tablePage=0;state.energy=null;
 state.energyInput={p1:'',p2:'',plan:'',confirmed:false};
 state.reportRunId=next.key;
 if(destination==='forecast')state.draft={origin:csvTime(run.origin).replace(' ','T').replace(/T(\d):/,'T0$1:').slice(0,16),horizon:run.horizon,turbines:run.turbines.length===2?'both':run.turbines[0]};
 state.page=destination;
 if(location.hash==='#'+destination){render();if(destination==='reports'){$('#selected-run-title')?.focus({preventScroll:true});if(matchMedia('(max-width:1000px)').matches)$('.analysis-panel')?.scrollIntoView({block:'start'});}else window.scrollTo(0,0);}else location.hash=destination;
}
function setStage(stage){run.stage=stage;run.quality=stage==='degraded'?'degraded':'passed';state.energy=null;render();}
function localPassport(){modal('Паспорт выпуска',`${pill('Демонстрационный выпуск','warn')}${kv([['Идентификатор макета',esc(run.key)],['Дата и время выпуска',`${csvTime(run.origin)}<br>Asia/Almaty`],['Окно прогноза',`${csvTime(run.points[0].valid_time)}<br>до ${csvTime(run.points.at(-1).interval_end)}`],['Фактическое выполнение','Не запускалось на сервере'],['Статус задания',stagePill(run.stage)],['Качество / объяснение',`${qualityText(run.quality)} / объяснение недоступно`],['Версия модели','Не подключена'],['Единица','Нормализованная мощность'],['Источник погоды','Не подключён'],['Проверка исторической доступности','Не выполнена']])}<p class="notice-text">Паспорт backend дополнит weather run, effective_available_at, availability_basis и версии модели / признаков. Эти поля нельзя заменять временем открытия интерфейса.</p><div class="modal-actions"><a href="#agent" class="button">Источники ${icon('arrow')}</a>${button('CSV иллюстрации','export','primary','download',!hasResult(run)?'disabled':'')}</div>`);}
function passport(){
 const first=run.points[0],last=run.points.at(-1),weather=run.weatherRuns?.[0];
 const window=first&&last?`${csvTime(first.valid_time)}<br>до ${csvTime(last.interval_end)}`:'Результат ещё не получен';
 modal('Паспорт выпуска',`${pill(run.remote?'Выпуск backend':'Локальная иллюстрация',run.mode==='real'?'ok':'warn')}${kv([
  ['Идентификатор',esc(run.key)],
  ['Дата и время выпуска',`${csvTime(run.origin)}<br>Asia/Almaty`],
  ['Окно прогноза',window],
  ['Статус задания',stagePill(run.stage)],
  ['Качество / объяснение',`${qualityText(run.quality)} / ${esc(run.explanation||'недоступно')}`],
  ['Версия модели',esc(run.model||'Не предоставлена')],
  ['Версия признаков',esc(run.featureVersion||'Не предоставлена')],
  ['Единица','Нормализованная мощность'],
  ['Источник погоды',esc(weather?.provider||'Не предоставлен')],
  ['Доступность погоды',weather?csvTime(weather.effective_available_at):'Не предоставлена'],
 ])}<p class="notice-text">${run.mode==='fixture'?'Синтетический режим разработки: значения не являются реальным прогнозом.':'Поля получены из результата backend.'}</p><div class="modal-actions"><a href="#agent" class="button">Источники ${icon('arrow')}</a>${button(run.remote?'CSV backend':'CSV иллюстрации','export','primary','download',!hasResult(run)?'disabled':'')}</div>`);
}
function bindChart(){
 const chartEl=$('#chart-container');if(!chartEl)return;
 chartEl.addEventListener('pointermove',e=>{
  // The chart can scroll independently on a phone. Use the SVG, not the viewport,
  // to map a pointer to its hour; otherwise the tooltip reports the wrong point.
  const rect=chartEl.getBoundingClientRect(),svgRect=chartEl.querySelector('svg').getBoundingClientRect();
  const i=Math.max(0,Math.min(run.horizon-1,Math.round(((e.clientX-svgRect.left)/svgRect.width*780-30)/735*(run.horizon-1))));
  const ps=run.points.filter((p,index)=>Math.floor(index/run.turbines.length)===i),tip=$('#chart-tooltip');
  tip.innerHTML=`${csvTime(ps[0].valid_time)}<br>${ps.filter(p=>state.chartTurbine==='both'||p.turbine_id===state.chartTurbine).map(p=>`Турбина ${p.turbine_id} · среднее ${num(p.power_mean)}<br>q10–q90: ${num(p.q10)} — ${num(p.q90)}`).join('<br>')}`;
  tip.style.display='block';tip.style.left=(chartEl.scrollLeft+Math.max(0,Math.min(e.clientX-rect.left+10,rect.width-215)))+'px';tip.style.top='10px';
 });
 chartEl.addEventListener('pointerleave',()=>$('#chart-tooltip').style.display='none');
}
async function startPreview(){
 if(!backend.available){toast(backend.message);return;}
 const turbines=state.draft.turbines==='both'?['1','2']:[state.draft.turbines];
 const origin=new Date(state.draft.origin+':00+05:00').toISOString();
 const next=makePreview({key:'pending',origin,horizon:state.draft.horizon,turbines,stage:'submitting'});
 next.points=[];next.remote=true;next.model=backend.modelVersion;next.mode='fixture';run=next;render();
 try{
  const job=await api.createForecast({forecast_origin:origin,horizon_hours:state.draft.horizon,turbine_ids:turbines.map(Number),mode:'replay',model_version:backend.modelVersion,data_mode:'fixture'},crypto.randomUUID());
  next.key=job.job_id;next.stage=job.status;history.unshift(next);await loadRun(next);toast('Прогноз принят backend и поставлен в очередь.');
  const result=await waitForForecast(job.job_id,current=>{next.stage=current.status==='completed'?'completed':current.status||'running';render();});
  attachResult(next,result);next.stage='completed';render();toast('Прогноз готов.');
 }catch(error){next.stage='failed';render();toast(error.message);}
}

function replayOrigins(from,to,time){
 const [year,month,day]=from.split('-').map(Number),end=Date.parse(`${to}T00:00:00Z`),origins=[];
 for(let cursor=Date.UTC(year,month-1,day);cursor<=end;cursor+=86400000){
  const date=new Date(cursor).toISOString().slice(0,10);
  origins.push(new Date(`${date}T${time}:00+05:00`).toISOString());
 }
 return origins;
}

async function refreshReplay(id){
 const [details,jobs]=await Promise.all([api.replayDetails(id),api.replayRuns(id)]);
 const known=new Map([...(state.replay?.children||[]),...history].map(item=>[item.key,item]));
 const children=await Promise.all(jobs.map(async job=>{
  const next=historyRun(await api.forecastDetails(job.job_id)),existing=known.get(job.job_id);
  if(existing?.points?.length)next.points=existing.points;
  return Object.assign(existing||{},next);
 }));
 state.replay={...state.replay,id,remote:true,status:details.job.status,counters:details.counters,children,details};
 render();
 return details;
}

async function startReplay(){
 const d=state.replayDraft,origins=replayOrigins(d.from,d.to,d.time);
 state.replay={remote:true,status:'submitting',children:[],counters:{total:origins.length,queued:origins.length,running:0,completed:0,failed:0,cancelled:0}};
 render();
 try{
  const job=await api.createReplay({origins,horizon_hours:d.horizon,turbine_ids:[1,2],model_version:backend.modelVersion,data_mode:'fixture'},crypto.randomUUID());
  state.replay={...state.replay,id:job.job_id,status:job.status};render();
  await refreshReplay(job.job_id);
  await waitForJob(job.job_id,current=>{if(!state.replay||state.replay.id!==job.job_id)return;state.replay.status=current.status||'running';render();});
  const details=await refreshReplay(job.job_id);
  toast(details.job.status==='completed'?'Пакет прогнозов готов.':'Пакет завершён не полностью.');
 }catch(error){state.replay={...state.replay,status:'failed',error:error.message};render();toast(error.message);}
}

async function loadRunExtras(target){
 if(!target?.remote||runExtras.get(target.key)?.loading)return;
 runExtras.set(target.key,{loading:true,events:[]});
 const tasks=[api.events(target.key),hasResult(target)?api.weather(target.key):Promise.resolve(null),hasResult(target)?api.explanation(target.key):Promise.resolve(null)];
 const [events,weather,explanation]=await Promise.allSettled(tasks);
 const failures=[events,weather,explanation].filter(item=>item.status==='rejected').map(item=>item.reason?.message||String(item.reason));
 runExtras.set(target.key,{loading:false,events:events.status==='fulfilled'?events.value:[],weather:weather.status==='fulfilled'?weather.value:null,explanation:explanation.status==='fulfilled'?explanation.value:null,error:failures.join(' · ')});
 if(state.page==='agent'&&run.key===target.key)render();
}

async function connectBackend(){
 try{
  const [meta,models,listing]=await Promise.all([api.meta(),api.models(),api.forecasts({limit:100})]);
  backend.available=Boolean(meta.capabilities?.forecast);
  backend.capabilities=meta.capabilities||{};
  backend.modelVersion=models.items.find(model=>model.availability==='ready')?.model_version||backend.modelVersion;
  backend.message=backend.available?'Backend подключён.':'Backend отключил создание прогнозов.';
  const remote=listing.items.map(historyRun),known=new Set(remote.map(item=>item.key));
  history.splice(0,history.length,...remote,...history.filter(item=>!known.has(item.key)&&!item.remote));
  const [evaluations,quality]=await Promise.allSettled([backend.capabilities.evaluations?api.evaluations({limit:100}):Promise.resolve({items:[]}),backend.capabilities.data_quality?api.dataQuality():Promise.resolve(null)]);
  state.evaluations=evaluations.status==='fulfilled'?evaluations.value.items:[];
  state.evaluationId=state.evaluations.find(item=>item.status==='available')?.evaluation_id||state.evaluations[0]?.evaluation_id||'';
  state.dataQuality=quality.status==='fulfilled'?quality.value:null;
  toast(backend.message);render();
 }catch(error){backend.message=`Backend недоступен: ${error.message}`;toast(backend.message);render();}
}
document.addEventListener('input',e=>{
 const el=e.target;
 if(el.id==='origin')state.draft.origin=el.value;
 if(!el.closest('#energy-form'))return;
 if(el.id==='energy-plan')state.energyInput.plan=el.value;
 if(el.id==='normalize-confirm')state.energyInput.confirmed=el.checked;
 if(el.id==='capacity-1')state.energyInput.p1=el.value;
 if(el.id==='capacity-2')state.energyInput.p2=el.value;
 if(!state.energy)return;
 state.energyDirty=true;
 const warning=$('#energy-stale');if(warning)warning.hidden=false;
 const exportButton=$('[data-action="export-energy"]');if(exportButton)exportButton.disabled=true;
});
document.addEventListener('change',e=>{
 const el=e.target;
 if(el.id==='origin')state.draft.origin=el.value;
 if(el.id==='turbines')state.draft.turbines=el.value;
 if(el.id==='report-run'&&el.value){void loadRun(history.find(r=>r.key===el.value),'reports');return;}
 if(el.id==='history-from'||el.id==='history-to')$('#history-to').setCustomValidity('');
 if(el.id==='energy-plan')state.energyInput.plan=el.value;
 if(el.id==='normalize-confirm')state.energyInput.confirmed=el.checked;
 if(el.id==='capacity-1')state.energyInput.p1=el.value;
 if(el.id==='capacity-2')state.energyInput.p2=el.value;
 if(el.id==='preview-state')setStage(el.value);
 if(el.id==='evaluation-report'){state.evaluationId=el.value;render();}
 if(el.id==='replay-state'){
  const b=state.replay;b.view=el.value;b.status=el.value==='partial'?'failed':el.value;
  b.children.forEach((r,i)=>{r.stage=el.value==='partial'?(i<Math.floor(b.children.length/2)?'completed':i===Math.floor(b.children.length/2)?'failed':'cancelled'):el.value;});render();
 }
});
document.addEventListener('submit',e=>{
 e.preventDefault();const form=e.target;
 if(form.id==='forecast-form'){state.draft.origin=$('#origin').value;state.draft.turbines=$('#turbines').value;void startPreview();}
 if(form.id==='history-form'){const from=$('#history-from').value,to=$('#history-to').value;if(from&&to&&from>to){$('#history-to').setCustomValidity('Дата «по» должна быть не раньше даты «с».');$('#history-to').reportValidity();return;}state.filters={...state.filters,from,to,turbine:$('#history-turbine').value,status:$('#history-status').value,mode:$('#history-mode').value};render();toast('Поиск обновлён. Если выбранного выпуска нет в списке, выберите другой.');}
 if(form.id==='energy-form'){
  const capacities=Object.fromEntries(run.turbines.map(t=>[t,Number($('#capacity-'+t).value)]));const plan=Number($('#energy-plan').value),confirmed=$('#normalize-confirm').checked;
  state.energyInput={p1:$('#capacity-1')?.value||'',p2:$('#capacity-2')?.value||'',plan:$('#energy-plan').value,confirmed};
  try{state.energy=energyScenario(run.points,{capacities,plan,confirmed,turbines:run.turbines});state.energyDirty=false;render();toast('Сценарий рассчитан на заданных вами допущениях.');}catch(error){toast(error.message);}
 }
 if(form.id==='replay-form'){
  const from=$('#replay-from').value,to=$('#replay-to').value,time=$('#replay-time').value,horizon=Number($('#replay-horizon').value);if(from>to){toast('Первый origin должен быть не позже последнего.');return;}
  const n=Math.round((Date.parse(to)-Date.parse(from))/86400000)+1;if(n>60){toast('Макет поддерживает до 60 origins за раз.');return;}
  state.replayDraft={from,to,time,horizon};
  if(backend.capabilities.replay)void startReplay();
  else {const batchId=crypto.randomUUID();state.replay={view:'queued',status:'queued',children:Array.from({length:n},(_,i)=>makePreview({key:`replay-${batchId}-${i+1}`,origin:new Date(Date.parse(from)+i*86400000).toISOString().slice(0,10)+'T'+time+':00+05:00',horizon,stage:'queued'}))};render();toast('Пакет создан в локальном макете.');}
 }
});
document.addEventListener('click',e=>{
 const homeRun=e.target.closest('[data-home-run]');
 if(homeRun){e.preventDefault();const next=history.find(r=>r.key===homeRun.dataset.homeRun);if(next){state.filters={from:'',to:'',turbine:'all',status:'all',mode:'all',sort:'desc'};navigationFocusRequested=true;void loadRun(next,'reports');}return;}
 const navLink=e.target.closest('.sidebar-nav a,.sidebar-brand,.home-header a,.home-cta,.home-run-link');
 if(navLink){navigationFocusRequested=true;closeNavigation(false);if(navLink.hash===location.hash){$('#page-title')?.focus();navigationFocusRequested=false;}return;}
 const target=e.target.closest('button,[data-open-run],[data-replay-run]');if(!target||target.disabled)return;
 if(target.dataset.horizon){state.draft.horizon=Number(target.dataset.horizon);render();return;}
 if(target.dataset.reportTab){state.reportTab=target.dataset.reportTab;render();return;}
 if(target.dataset.chartTurbine){state.chartTurbine=target.dataset.chartTurbine;render();return;}
 if(target.dataset.openRun){loadRun(history.find(r=>r.key===target.dataset.openRun),'reports');return;}
 if(target.dataset.replayRun){const child=state.replay.children.find(r=>r.key===target.dataset.replayRun);if(!history.includes(child))history.unshift(child);state.filters={from:'',to:'',turbine:'all',status:'all',mode:'all',sort:'desc'};loadRun(child,'reports');return;}
 const action=target.dataset.action;
 if(action==='sidebar-toggle'){sidebarCollapsed=!sidebarCollapsed;try{localStorage.setItem('aura-sidebar-collapsed',String(sidebarCollapsed));}catch{}syncSidebar();return;}
 if(action==='menu-open'){openNavigation(target);return;}
 if(action==='menu-close'){closeNavigation();return;}
 if(action==='help')closeNavigation();
 if(action==='toggle-quantiles'){state.quantileDetails=!state.quantileDetails;render();}
 if(action==='show-analysis'||action==='show-hourly'){
  if(history.includes(run)){state.reportRunId=run.key;if(!visibleSelection(filterHistory(history,state.filters),run.key))state.filters={from:'',to:'',turbine:'all',status:'all',mode:'all',sort:'desc'};}
  if(action==='show-hourly')state.reportTab='hourly';
  if(state.page==='reports'){render();if(action==='show-hourly')$('[data-report-tab="hourly"]')?.focus();}else location.hash='reports';
 }
 if(action==='reading-size'){state.largeText=!state.largeText;try{localStorage.setItem('aura-large-text',String(state.largeText));}catch{} document.body.classList.toggle('large-text',state.largeText);document.querySelectorAll('[data-action="reading-size"]').forEach(el=>el.setAttribute('aria-pressed',String(state.largeText)));toast(state.largeText?'Включён крупный текст.':'Включён обычный размер текста.');}
 if(action==='close')closeModal();
 if(action==='passport')passport();
 if(action==='export'&&hasResult(run)){if(run.remote)api.exportForecast(run.key).then(blob=>downloadBlob(blob,`AURA-${run.key}.csv`)).catch(error=>toast(error.message));else download(previewCSV(run),`AURA-SYNTHETIC-UI-${run.key}.csv`);}
 if(action==='new-preview'){closeModal();run=makePreview({key:'new-draft',stage:'initial',origin:state.draft.origin+':00+05:00',horizon:state.draft.horizon,turbines:state.draft.turbines==='both'?['1','2']:[state.draft.turbines]});state.page='forecast';state.energy=null;state.tablePage=0;location.hash='forecast';render();$('#origin')?.focus();}
 if(action==='cancel')modal('Отменить задание?','<p>В продукте это отдельный POST /api/jobs/{id}/cancel. Закрытие этой вкладки не отменяет расчёт.</p><p>В макете покажем состояние «Отмена запрошена», затем подтверждение можно выбрать вручную.</p><div class="modal-actions">'+button('Не отменять','close','ghost','close')+button('Запросить отмену','confirm-cancel','danger','check')+'</div>');
 if(action==='confirm-cancel'){closeModal();if(run.remote){run.stage='cancel_requested';render();api.cancel(run.key).then(job=>{run.stage=job.status;render();toast('Backend принял запрос отмены.');}).catch(error=>{toast(error.message);void api.job(run.key).then(job=>{run.stage=job.status;render();});});}else setStage('cancel_requested');}
 if(action==='next-page'){state.tablePage++;render();}
 if(action==='prev-page'){state.tablePage--;render();}
 if(action==='sort-history'){state.filters.sort=state.filters.sort==='desc'?'asc':'desc';render();}
 if(action==='reset-history'){state.filters={from:'',to:'',turbine:'all',status:'all',mode:'all',sort:'desc'};render();}
 if(action==='export-energy'&&state.energy&&!state.energyDirty){const header='data_mode,valid_time,power_kw,energy_kwh,plan_kwh,scenario_deficit_kwh,surplus_kwh';download([header,...state.energy.rows.map(r=>['synthetic_ui_scenario',r.time,...(r.complete?[r.power,r.energy,r.plan,r.deficit,r.surplus].map(v=>v.toFixed(4)):['','','','',''])].join(','))].join('\r\n'),'AURA-SCENARIO-energy.csv');}
 if(action==='export-replay'){
  const b=state.replay,completed=b.remote?b.counters.completed:b.children.filter(hasResult).length,total=b.remote?b.counters.total:b.children.length,partial=completed<total;
  modal(partial?'Скачать частичный результат?':'Скачать пакет?',`<p>Готово ${completed} из ${total} выпусков. ${partial?'Backend включит только завершённые и пометит экспорт как частичный.':'Backend включит все завершённые выпуски.'}</p><p>${b.remote?'CSV формирует Go backend.':'Локальный файл будет помечен SYNTHETIC-UI.'}</p><div class="modal-actions">${button('Отмена','close','ghost','close')}${button(partial?'Скачать частичный CSV':'Скачать CSV','confirm-replay-export','primary','download')}</div>`);
 }
 if(action==='confirm-replay-export'){
  const b=state.replay;
  if(b.remote){const partial=b.counters.completed<b.counters.total;api.exportReplay(b.id,partial).then(result=>{downloadBlob(result.blob,`AURA-${result.status==='partial'?'PARTIAL-':''}${b.id}.csv`);closeModal();}).catch(error=>toast(error.message));}
  else {const ok=b.children.filter(hasResult),partial=ok.length<b.children.length,chunks=ok.map(previewCSV);download(chunks.map((c,i)=>i?c.split('\r\n').slice(1).join('\r\n'):c).join('\r\n'),`AURA-${partial?'PARTIAL-':''}SYNTHETIC-UI-replay.csv`);closeModal();}
 }
 if(action==='energy-help')modal('кВт, кВт·ч и потери','<p><strong>кВт</strong> — мощность. <strong>кВт·ч</strong> — энергия за интервал. Запись «кВт/ч» означает другую величину и здесь не используется.</p><p>Для пересчёта нормализованной мощности нужны подтверждённый способ нормализации и номиналы турбин. Для расчётной докупки — почасовой план поставки.</p><p>Реальные покупки требуют данных сделок. Физические потери требуют учёта доступной мощности, ограничений, простоев или потерь линии. Разница «план − прогноз» не доказывает физическую потерю.</p>');
 if(action==='help')modal('Как пользоваться AURA','<p><strong>1. Прогноз:</strong> выберите дату, время и турбины. <strong>2. История и анализ:</strong> выберите выпуск, затем «По часам», «График» или «План энергии».</p><p>Зелёная сплошная линия — средняя мощность турбины 1, синяя пунктирная — турбины 2. q50 — медиана, она не обязана совпадать со средним.</p><p>Заливка — q10–q90 для каждой турбины. Интервал станции нельзя получить простым сложением квантилей. В этом макете кривые иллюстративные; калибровка не подтверждена.</p><p>Первый столбец таблицы — начало часового интервала. Все API-времена отображаются в Asia/Almaty. В исходных CSV зона времени неизвестна.</p>');
 if(action==='prototype-info')modal('Статус реализации',`<p>Интерфейс подключён к Go backend: прогнозы, история, replay, события SSE с polling fallback, отмена, погода, объяснения, оценки, аудит данных и CSV используют канонический API.</p><p>${esc(backend.message)}</p><p>В режиме fixture все результаты синтетические и не подтверждают качество реальной модели.</p>`);
 if(action==='more')modal('Дополнительные возможности',[['replay','Прогнозы за период','repeat'],['quality','Качество модели','shield'],['agent','Источники и работа системы','spark'],['data','Исходные данные','database']].map(([hash,label,symbol])=>`<a class="nav-link" href="#${hash}">${icon(symbol)}${label}${icon('arrow')}</a>`).join('')+button('Как пользоваться','help','ghost','help'));
});
window.addEventListener('hashchange',()=>{if(location.hash==='#main'){$('#main').focus();return;}navigate();});
navigate();
void connectBackend();
