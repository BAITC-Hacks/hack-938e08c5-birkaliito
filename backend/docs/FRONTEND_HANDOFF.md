# Подключение фронтенда

Основной контракт — [OpenAPI](../api/openapi.yaml). Готовые [TypeScript-типы](../contracts/typescript/api-types.ts) и [клиент](../contracts/typescript/client.ts) не зависят от React. После запуска Go по адресу `http://127.0.0.1:8080/docs` доступен просмотр схемы. Статические снимки ответов удалены по запросу; живые ответы можно получить через mock API.

## Базовый сценарий

```ts
import { WindClient } from '../contracts/typescript/client';

const api = new WindClient(''); // настройте dev proxy для /api к Go
const meta = await api.getMeta();
const models = await api.listModels();
const key = crypto.randomUUID(); // сохраните для повторной попытки того же действия
const job = await api.createForecast({
  forecast_origin: '2026-01-31T18:00:00Z',
  model_version: 'fixture-not-trained',
  data_mode: 'fixture',
}, key);

const stream = api.subscribeJobEvents(job.job_id, {
  onEvent: event => console.log(event.node, event.message),
  onEnd: async final => {
    if (final.status === 'completed') console.log(await api.getResult(job.job_id));
    else console.log(await api.getJob(job.job_id));
  },
  onError: error => console.error(error),
});
// При размонтировании компонента: stream.close(). Это не отменяет задание.
```

`POST /api/forecast-runs` возвращает `202` и задание. Читайте `GET /api/jobs/{id}` и события, пока статус не станет `completed`, `failed` или `cancelled`. `job_id == run_id` для прогноза. Пользовательскую отмену отправляйте отдельно через `cancelJob`. Для нового действия нужен новый `Idempotency-Key`; при повторе уже отправленного запроса сохраняйте прежний ключ и тело. Изменение тела с тем же ключом возвращает 409.

По умолчанию API подставляет `horizon_hours=48`, `turbine_ids=[1,2]`, `mode=replay`, `data_mode=real`. **Для mock обязательно явно указать `data_mode=fixture`.** Доступны горизонты 24 и 48 часов; origin должен содержать смещение времени и после преобразования в UTC приходиться на целый час. Выходные даты — UTC. `valid_time` обозначает начало часового интервала, `interval_end` — конец. Для двух турбин и 48 часов результат содержит 96 точек.

## События и ошибки

`subscribeJobEvents` использует SSE `/api/jobs/{id}/stream`, учитывает `event_id` и при ошибке связи переключается на опрос `/events` и `/jobs`. `stream_end` закрывает подписку. При размонтировании вызывайте `close()`. Отключение клиента не меняет статус задания. Если сервер ответил 410, история событий уже истекла; покажите ошибку и запросите текущее состояние задания.

Неуспешные HTTP ответы дают `ApiException` с `status` и `{code,message,request_id}`. У списков обычно есть `{items,next_cursor}`; события и дочерние задания replay возвращаются массивом. Курсор истории непрозрачен и привязан к фильтрам: при смене фильтра начинайте с первой страницы.

Для Vite/React настройте dev proxy для `/api`, `/healthz`, `/readyz`, `/docs`, `/openapi.yaml` на `http://127.0.0.1:8080`. Python-токен остаётся только на сервере; `VITE_*` для него не используйте.

## Честное отображение

При `data_mode=fixture` всегда показывайте «Синтетические данные — режим разработки». `fixture-not-trained` не является обученной моделью. Mock возвращает синтетические погоду и метрики; SHAP сейчас недоступен. Не показывайте MW/MWh, фактическую мощность за февраль или реальную точность: этих подтверждённых данных нет. `normalized_power` не имеет подтверждённого перевода в MW. Пропущенные показатели — `null`/`unavailable`, а не ноль. Интервал q10–q90 не является гарантией.

Для графика используйте `turbine_id`, `valid_time`, `power_mean`, `q10`, `q90`. Поле `q50` теперь может быть `null`: ML-модель не оценивает медиану, поэтому линию медианы показывайте только при числовом значении. Для replay пересекающиеся `valid_time` относятся к разным моментам выпуска и не должны сливаться без отдельного правила. CSV прогнозов и replay получает клиент через `exportForecast` и `exportReplay`; для неполного replay требуется `allowPartial=true`, а заголовок экспорта помечает частичный результат.

Для демонстрации состояний можно запускать backend с `MOCK_SCENARIO=success`, `degraded`, `failure`, `slow`, `llm_unavailable` или `weather_future`. Сценарий задаётся до запуска контейнера или процесса. Эти состояния создаёт симулятор, а не ML.
