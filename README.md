# Прогнозирование выработки ветроэнергии

В репозитории находятся:
1. **[design](design/DESIGN.md)**: Frontend интерфейс AURA (запускается на порту 4173)
2. **[backend](backend/README.md)**: Go/Gin REST API (собирает задачи, работает с фронтендом, порт 8080)
3. **[ml](ml/README.md)**: Python ML-сервис (XGBoost), который прогнозирует выработку на 24-48 часов вперед, используя GFS погоду от Open-Meteo и исторические датасеты SCADA.

Обе части связаны в единую Agentic AI систему! Backend обращается к ML-сервису по HTTP-протоколу для получения ML-прогнозов, а Frontend AURA обращается к Backend.

## Запуск системы (Frontend + Backend + ML)

Вам нужен только Docker с поддержкой Compose. Из корня репозитория выполните команды:

```sh
cd backend
docker compose up --build -d
```

Эта команда поднимет **одновременно Frontend (AURA), Go API и Python ML-сервис**.
- **Frontend интерфейс:** <http://localhost:4173>
- **API Swagger документация:** <http://127.0.0.1:8080/docs>

Первый запуск займет некоторое время для скачивания библиотек. Для остановки сервисов используйте `docker compose down`.

## Дополнительная информация
Контракт для фронтенда: [OpenAPI](backend/api/openapi.yaml), [TypeScript-типы](backend/contracts/typescript/api-types.ts), [клиент](backend/contracts/typescript/client.ts), [порядок подключения](backend/docs/FRONTEND_HANDOFF.md). 
Реальные возможности и ограничения описаны в [README backend](backend/README.md).
