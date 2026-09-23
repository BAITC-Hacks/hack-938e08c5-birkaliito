# Прогнозирование выработки ветроэнергии

В репозитории находятся:
1. **[backend](backend/README.md)**: Go/Gin REST API (собирает задачи, работает с фронтендом).
2. **[ml](ml/README.md)**: Python ML-сервис (XGBoost), который прогнозирует выработку на 24-48 часов вперед, используя GFS погоду от Open-Meteo и исторические датасеты SCADA.

Обе части связаны в единую систему! Backend обращается к ML-сервису по HTTP-протоколу для получения реальных ML-прогнозов.

## Запуск системы (Backend + ML)

Вам нужен только Docker с поддержкой Compose. Из корня репозитория выполните команды:

```sh
cd backend
docker compose up --build -d
```

Эта команда поднимет **одновременно и Go API, и Python ML-сервис**.
- API: <http://127.0.0.1:8080>
- Swagger документация: <http://127.0.0.1:8080/docs>

Первый запуск займет некоторое время для скачивания библиотек. Для остановки сервисов используйте `docker compose down`.

## Фронтенд
Контракт для фронтенда: [OpenAPI](backend/api/openapi.yaml), [TypeScript-типы](backend/contracts/typescript/api-types.ts), [клиент](backend/contracts/typescript/client.ts), [порядок подключения](backend/docs/FRONTEND_HANDOFF.md). 
Когда появится фронтенд, его так же можно будет добавить в `backend/compose.yaml`.
