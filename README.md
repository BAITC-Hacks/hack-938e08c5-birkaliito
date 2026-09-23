# Прогнозирование выработки ветроэнергии

В папке [backend](backend/README.md) находится Go/Gin API. Сейчас он запускается с синтетическим прогнозом (`fixture`) для подключения фронтенда. Обученной ML-модели и Python-сервиса в этом репозитории пока нет.

## Запуск на любом ноутбуке

Нужен Docker с поддержкой Compose. Из корня репозитория выполните две команды:

```sh
cd backend
docker compose up --build
```

API: <http://127.0.0.1:8080>, документация: <http://127.0.0.1:8080/docs>. Первый запуск загружает зависимости и требует интернет. Остановка — `Ctrl+C`; данные mock хранятся в памяти и после остановки исчезают.

Контракт для фронтенда: [OpenAPI](backend/api/openapi.yaml), [TypeScript-типы](backend/contracts/typescript/api-types.ts), [клиент](backend/contracts/typescript/client.ts), [порядок подключения](backend/docs/FRONTEND_HANDOFF.md). Подробности, реальные возможности и ограничения — в [README backend](backend/README.md).

Когда появятся фронтенд и ML-сервис, их можно добавить в один Compose-проект. Текущий Compose запускает только Go API: обещать запуск всей системы одной командой пока рано.
