# AURA — дизайн v2 / Black × Acid Yellow

Обновлено 23.09.2026 по референсам пользователя и `FRONTEND_HANDOFF.md`.
Это интерактивный дизайн-прототип, а не работающая ML/Agentic AI-система.
Команда готовит `baseline_contracts`; пользователь подтвердил, что файлы ещё в работе.
API, GFS, ML, SSE, реальные jobs и отчёты не подключены. Go раздаёт только статику.

## Запуск и файлы

```bash
cd design
go run main.go
# http://localhost:4173/#forecast

# В другом терминале, из корня репозитория:
node --test design/model.test.mjs
```

После изменения embedded-файлов перезапустить `go run main.go` и обновить браузер.
Node нужен только для тестов; frontend работает без npm, Go-сервер без внешних модулей.
Manrope загружается из Google Fonts; без сети работает системный font fallback.

- `index.html` — общая оболочка, навигация, dialog, toast.
- `styles.css` — токены, компоненты и адаптивные раскладки.
- `app.js` — рендер экранов и пользовательские взаимодействия.
- `model.mjs` — исключительно представление для UI и формулы сценария; НЕ API DTO или mock сервера.
- `model.test.mjs` — тесты времени, истории, статусов, энергетического баланса, экспорта.
- `assets/wind-studio.png` — генеративный декоративный рендер, не фотография реальной ВЭС.
- `previews/v2-*.jpg` — актуальные скриншоты. Прежние `desktop.jpg`, `mobile.jpg`, `tablet.jpg`, `mobile-passport.jpg` относятся к старой зелёной версии, не к v2.

## Направление дизайна

Референсы адаптированы, а не скопированы: индустриальный рендер турбин, измерительный
индикатор, компактные карточки, погодная ясность почасовой ленты и дисциплина
финансовой таблицы. Нерелевантные RPM, угол лопастей, потребление домохозяйств,
давление и состояние редуктора не добавлялись: этих данных нет в контракте.

| Токен | Значение | Назначение |
|---|---|---|
| bg | #0B0C0D | Общий фон |
| panel | #141617 | Карточки |
| panel2 | #1B1E20 | Элементы управления |
| border | #2A2D2E | Границы |
| text | #F4F5EF | Основной текст |
| muted | #969C9D | Вторичный текст |
| accent | #EDFF45 | Главные действия, турбина 1 |
| turbine2 | #B6BFC7 | Турбина 2, пунктир |
| warning | #F0B46C | Предупреждения |
| error | #F09292 | Ошибки |

Это авторская палитра в духе запрошенного yellow/black, не заявление об официальных
HEX Higgsfield. Жёлтый зарезервирован под акценты. Семантика не зависит только от цвета:
подписи, иконки и пунктир дополняют цвет.

## Информационная архитектура

Сверху: Прогноз / Аналитика / **История** / Replay / Качество.
Слева: те же разделы + Агент и источники / Исходные данные / Справка.
На телефоне: Прогноз / Аналитика / История / Ещё. В «Ещё» доступны остальные экраны.
Плашка «Синтетические данные — режим разработки» есть на каждом экране.

| Экран | Реализованный UX | После API-интеграции |
|---|---|---|
| Прогноз | Origin, 24/48, 1/2 турбины; mean и отдельные q10–q90; паспорт; CSV-пример | Версии/capabilities из meta/models; POST, подписка, настоящий result |
| Аналитика | Таблица с датой/временем первой; q50 отдельно; пагинация; сценарий кВт/кВт·ч | Точки из канонического ForecastResult |
| История | Фильтры с–по, турбина, статус, режим; сортировка; открытие старого выпуска | Cursor pagination и реальные saved jobs |
| Replay | Диапазон ежедневных origins, дочерние задания, счётчики; явный partial export | Настоящий пакет, POST cancel, SSE/polling |
| Качество | Честный unavailable state, MAE/RMSE/bias/coverage и ширина без fake-значений | Метрики + baseline + evaluation_scope |
| Агент | Схема этапов, пустая реальная лента; weather provenance, LLM/SHAP unavailable | Реальные AgentEvent и проверяемые артефакты |
| Исходные данные | Проверенные агрегаты двух CSV и первые шесть реальных строк | Аудит из /api/data-quality |

## Пользовательские потоки

### 1. Прогноз

Origin → горизонт → турбины → допустимая модель → запуск → queued/running →
completed → график → почасовая таблица → паспорт / CSV.

В макете «Запуск · макет» создаёт локальный пример queued. Переходы управляются
явно через «Проверка UX-состояний» внизу. Нет таймеров, выдуманного процента
или заранее написанных мыслей, выдаваемых за работу AI. Реального выполнения нет.

В production новая форма не должна изменять предыдущий результат. Новый origin /
горизонт вступает в силу после отдельного запуска. Сохранять job_id и запрос.

### 2. История

Верхняя вкладка История → с / по (включительно) → дополнительные фильтры →
Применить → сортировка → открыть конкретный выпуск. Фильтр относится к **origin**
в Asia/Almaty, не к valid_time. Перекрывающиеся прогнозы не удаляются.
Ключ точки как минимум `(origin, valid_time, turbine_id)` в контексте выпуска/версии.
Сравнение разных выпусков пока описано визуально, отдельный мульти-origin график
не реализован; при добавлении подписывать origin каждой серии.

### 3. Энергия и дефицит

Аналитика → известные номиналы выбранных турбин → допущение Pnorm = P/Pном →
почасовой план станции → сценарий → итог/почасовой баланс → CSV.

До ввода исходных параметров энергия и дефицит — «—», не нули.
Чекбокс не подтверждает физику оборудования: он явно фиксирует пользовательское
допущение для сценария. В production заменить подтверждением от организаторов /
метаданными нормализации. Результат всегда подписан «сценарий, не факт».

```
P_i,kW = power_mean_i × Pnom_i          (только при верной нормализации)
P_station = Σ P_i,kW                    (в одном и том же часовом интервале)
E_station,kWh = P_station × Δt_hours    (здесь проверяется Δt = 1)
deficit_hour = max(plan_hour − E_station, 0)
surplus_hour = max(E_station − plan_hour, 0)
total_deficit = Σ deficit_hour         (не max(сумма плана − сумма E, 0))
```

План пока постоянный для всех часов: это упрощённый калькулятор сценария, не загрузка
реального почасового графика поставки. В дальнейшем добавить план по каждому часу.
Неполная пара турбин исключается из энергетического итога и отмечается; пропуски
не превращаются в нули. Для одной турбины считать только выбранную турбину и её план.
Докупка — расчётная потребность относительно плана, не совершённая сделка.
Физические потери / простой / curtailment из этих CSV не определяются.
Нет тарифов и правил небаланса — нет денежного ущерба.
Дефицит по среднему прогнозу не равен математическому ожиданию дефицита.

### 4. Replay

Диапазон origins + час + горизонт → пакет → child counters → любой завершённый
выпуск. Отдельный переключатель показывает queued / частичный сбой / completed /
cancelled. Успешные дети остаются доступны при failed родителе.
«Частичный CSV» → явное подтверждение с числом готовых / всего → файл PARTIAL.
В имени и содержимом экспорта остаётся synthetic UI label.

Февраль содержит 672 целевых часа на турбину. Перекрывающиеся 48-часовые выпуски
дают больше строк. Это не ошибка; часы за границами февраля исключаются из его оценки.

## Состояния

| Состояние | График / CSV | Основное поведение |
|---|---|---|
| initial | Нет | Пустая форма и приглашение к запуску |
| submitting | Нет | Отправка; повторная кнопка недоступна |
| queued | Нет | Ожидание; отдельная отмена |
| running | Нет | Этап из события; без фальшивого процента |
| completed | Да | Числа, паспорт, экспорт |
| completed + degraded | Да | Предупреждение о снижении качества |
| failed | Нет | Ошибка с будущими code/message/request_id |
| cancel_requested | Нет | Отдельный флаг, JobStatus ещё running |
| cancelled | Нет | Новый запуск отдельно |
| Python unavailable | Нет | 503 и действие повторного запуска |
| LLM unavailable | Да | ExplanationStatus unavailable, числа доступны |
| metrics unavailable | Да для прогноза | Страница метрик показывает пустое состояние |

JobStatus, QualityStatus и ExplanationStatus не взаимозаменяемы. В макете
селектор объединяет некоторые комбинации только для удобства UX-проверки.
Транспортный контракт при этом не определяется. Ноль мощности — корректное значение.

## Время и единицы

- Основная единица: **Нормализованная мощность**. Не MW/MWh и не % фактической выработки.
- power_mean и q50 — разные поля. Квантили турбин не складываются.
- q10–q90 — интервалы модели, не гарантия фактического покрытия 80%; требуется калибровка.
- valid_time — начало интервала, interval_end — конец. Оба доступны в таблице и CSV.
- Первый столбец отображает формат CSV `2026-02-01 0:00:00` (без ведущего нуля часа).
- API-время с offset/UTC → отображение Intl в Asia/Almaty.
- Origin и реальное executed_at — разные факты. В макете сервер не запускался:
  фактическое время выполнения **не выдумывается** из текущего времени браузера.
- Зона исходного CSV остаётся неизвестной; его строки не переинтерпретируются как UTC.

## Передача React / Go команде

Верстка намеренно независима от данных: её можно переносить в React-компоненты
`AppShell`, `ForecastForm`, `PowerChart`, `RunContext`, `HourlyTable`, `EnergyScenario`,
`HistoryFilters`, `ReplayPanel`, `EvaluationEmpty`, `AgentSources`, `RunPassport`.
Сам React-проект пока не создан: это переносимый HTML/CSS/JS макет.

После получения baseline_contracts:

1. Добавить **канонические** types.ts, OpenAPI и fixtures без переименования полей.
2. Удалить иллюстративные точки/историю из production adapter, оставить только в storybook/demo.
3. Форму строить по /api/meta, /api/models, /api/turbines. Неизвестные мощности = null.
4. POST /api/forecast-runs строго по example_request.fixture.json, один уникальный
   Idempotency-Key на намерение. Сетевой retry = тот же ключ И то же тело.
5. 202 означает принятие job, не завершение. Хранить returned job_id; не создавать ID на клиенте для API.
6. SSE agent_event: dedup(job_id,event_id), after / Last-Event-ID. Heartbeat не рисовать.
   stream_end → close(); stream_error отдельно; reconnect с cursor; fallback job/events polling.
7. 409 RESULT_NOT_READY — нормальное ожидание результата. 409 IDEMPOTENCY_CONFLICT —
   конфликт ключа. 410 — восстановление после истёкшего cursor; 501 — скрыть unsupported
   действие по capabilities; 503 — зависимость недоступна. Ошибка плоская, без envelope.
8. Cancel = отдельный POST. Закрыть вкладку = закрыть подписку, не отменить job.
9. completed → result/details; weather/explanation/SHAP только при capability.
   LLM отображать текстом (textContent / React text), без dangerouslySetInnerHTML.
10. История — серверные фильтры + `{items,next_cursor}`. Replay partial export только явно.
11. Браузер ходит только в Go через same-origin proxy. Python / LLM keys не в frontend env.
12. Расширения DTO брать из общего OpenAPI после синхронизации, не из этого макета.

Согласованные endpoint paths сохранены в исходном FRONTEND_HANDOFF.md. Этот файл
не заменяет его и не утверждает, что новые маршруты уже реализованы.

## Адаптивность и доступность

- >1150 px: узкая боковая панель, верхние табы, hero + summary, chart + context.
- 901–1150 px: более компактная сетка и перенос формы, семантика сохранена.
- 601–900 px: hero и summary последовательно; график в полную ширину.
- ≤600 px: одна колонка, нижняя навигация, «Ещё»; История остаётся и сверху.
- Таблицы скроллятся **внутри** карточек, не раздвигают страницу.
- Native controls, labels, aria-current, focus-visible, dialog с Escape и focus trap,
  aria-live для уведомлений, prefers-reduced-motion. Не применяются бесконечные анимации.
- Доступен skip-link. Числа с tabular-nums, критичные предупреждения текстовые.

Проверено в браузере: 1440×1050, 768×1024, 390×844. На 390 px все семь экранов
имеют documentWidth = viewportWidth, без горизонтального скролла страницы.
Пройдены: queued → cancel_requested → cancelled, Python unavailable без графика,
LLM unavailable с доступным графиком и CSV, расчёт энергии, фильтр истории на один
origin-day, replay partial 14 completed / 1 failed / 13 cancelled, подтверждение
частичного экспорта, мобильное меню. JS console errors не обнаружены.
Логические unit-тесты: 7 passed. Это не проверка API или ML.

## Рендер турбин / imagegen

Использован навык imagegen и встроенный инструмент генерации (не CLI).
Файл: `assets/wind-studio.png`. Генеративная иллюстрация, не технический digital twin.
Финальный prompt:

> Use case: stylized-concept. Asset type: background hero artwork for an operational wind energy dashboard, no UI rendered into image. Create a premium cinematic realistic 3D render of two elegant modern three-blade wind turbines in a pitch-black / charcoal studio environment, sculptural silver titanium blades and white satin towers. Dominant large wind turbine on the right, a second smaller one just left of it and deeper into the scene. Strong perspective looking slightly upward at the nacelles. The blades are sharp and mechanically plausible. Restrained acid yellow rim light on some edges and tiny warm yellow reflections, grayscale otherwise. Smooth volumetric haze, very subtle thin concentric orbital arcs behind the turbine to suggest air, restrained luxury industrial art direction, no busy landscape, no sky, no buildings, no sun. Wide landscape composition 1536x1024. Turbines occupy right 65 percent; left 35 percent is very dark clean negative space where HTML text will be overlaid. The base fades seamlessly into #101110 charcoal. Rich tactile materials and excellent silhouette, ultra clean, no text, no numbers, no logos, no watermark, no embedded dashboard, no people.
