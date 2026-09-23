# Прогнозирование выработки ветроэнергии

В репозитории находятся Go/Gin API и адаптивный интерфейс AURA. Backend сейчас
работает с синтетическим прогнозом (`fixture`) для интеграции фронтенда;
обученной ML-модели и Python-сервиса в репозитории пока нет.

## Запуск backend

Нужен Docker с поддержкой Compose. Из корня репозитория:

```sh
cd backend
docker compose up --build
```

API будет доступен по адресу <http://127.0.0.1:8080>, документация —
<http://127.0.0.1:8080/docs>. Первый запуск загружает зависимости и требует
интернет. Остановка — `Ctrl+C`; данные mock хранятся в памяти и после остановки
исчезают.

Контракт для фронтенда: [OpenAPI](backend/api/openapi.yaml),
[TypeScript-типы](backend/contracts/typescript/api-types.ts),
[клиент](backend/contracts/typescript/client.ts) и
[порядок подключения](backend/docs/FRONTEND_HANDOFF.md). Реальные возможности и
ограничения описаны в [README backend](backend/README.md).

## Запуск AURA

Во втором терминале из корня репозитория:

```sh
cd design
go run main.go
```

Откройте <http://localhost:4173/#forecast>. Сервер интерфейса проксирует `/api`,
`/healthz`, `/readyz`, `/docs` и `/openapi.yaml` на backend по адресу
`http://127.0.0.1:8080`.

Интерфейс использует канонический API для прогнозов, истории, replay, SSE с
polling fallback, отмены, погоды, объяснений, оценок, аудита данных и CSV.
Результаты `fixture` всегда отмечаются как синтетические и не подтверждают
качество реальной модели.

Проверка frontend-логики:

```sh
node --test design/model.test.mjs design/api.test.mjs
```

[Спецификация UX и дизайн-система](design/DESIGN.md). Актуальные превью:
[ноутбук](design/previews/v3-desktop.jpg) и
[планшет](design/previews/v3-tablet.jpg).

Текущий Docker Compose запускает только Go API. Frontend запускается отдельной
командой выше; Python/ML-сервис пока не включён.
