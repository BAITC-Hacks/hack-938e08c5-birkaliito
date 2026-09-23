# AURA — главная страница

Новый вход: `http://localhost:4173/#home`. Пустой hash тоже открывает главную.
Существующие `#forecast`, `#reports`, `#replay`, `#quality`, `#agent`, `#data`
сохранены. Backend, контракты API и формулы прогноза не менялись.

Главная повторяет направление предоставленного референса, но не его данные:
светлая фотографическая сцена, зелёная типографика, одна основная кнопка,
карточка последнего готового выпуска. Числа 2 / 24–48 ч / 1 час — параметры
этого кейса, не обещания мощности, экономии или точности.

Карточка использует существующую историю и адаптер backend. Готовые серверные
выпуски имеют приоритет над локальными иллюстрациями. Переход открывает тот же
идентификатор выпуска через существующий `loadRun`; фильтры истории сбрасываются,
чтобы выбранная запись была видна. Режим `real | fixture` соответствует контракту.
При отсутствии backend иллюстрация явно отмечена «Демо»; создание прогноза
недоступно. Запоздалый ответ загрузки не перебивает новый переход пользователя.

На рабочие страницы возвращается левая навигация. На мобильной главной —
модальное меню с Escape и возвратом фокуса, в том числе после перерисовки страницы.

## Изображение

- Файл проекта: `design/assets/wind-landscape.png` (1,8 MB).
- Абсолютный путь: `/Users/birkhanym/hackathon-aura-winners/hack-938e08c5-birkaliito/design/assets/wind-landscape.png`.
- Создано встроенным инструментом imagegen. CLI/API fallback не использовался.
- Изображение декоративное, без текста и встроенных кнопок. Это не фотография
  реальной станции. Весь интерфейс поверх — доступные HTML-элементы.

Финальный промпт:

> Use case: photorealistic-natural. Asset type: background photograph for a renewable wind energy forecasting web homepage, not a UI screenshot. Create an original high-end photorealistic editorial landscape, wide 16:10 composition. Soft green rolling hills occupy lower third; pale blue and white sky with a few soft clouds above. One enormous realistic white wind turbine viewed front-on in close-up, hub at about 61% width and 68% height. Three elegant physically plausible turbine blades radiate from the hub: one blade rises and exits the top edge, two diagonal blades reach bottom corners. White tower descends to bottom. Pale matte white clean engineering surfaces, realistic seams, natural midday diffuse sunlight, calm inviting atmosphere. The left 40% upper-middle image must be open pale sky, clean and low-detail for dark-green HTML headline later. Right upper-middle sky area also quiet for a separate information panel. Camera elevated at rotor height, scenic hills behind. Natural restrained spring green, white, and pale sky blue, not neon. No people, no buildings, no extra turbine rows. No text, letters, logos, watermarks, buttons, charts, borders, or interface elements. This is an original image inspired by a wind power website art direction; not a copy of any branding.

## Проверка

`node --test design/model.test.mjs design/api.test.mjs` — 12 тестов.
Проверены 320/390/768/1440 px, крупный текст, меню и возврат фокуса. После
подключения backend карточка открыла тот же fixture-выпуск из API; таблица
отобразила его почасовые значения. Ошибок JavaScript в проверенной вкладке нет.
Полный запуск реального прогноза требует доступного backend на 8080;
создание заданий во время дизайнерской проверки не выполнялось.
