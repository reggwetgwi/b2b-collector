# B2B Collector

> **EN:** Desktop app (Tkinter + PyInstaller) that builds B2B prospect lists for a
> given niche and city. Discovers companies through SERP providers, enriches them
> from open registries (tax ID, legal entity, official phone numbers), pulls ratings
> from map services, checks search positions, deduplicates by fuzzy name matching
> and exports a formatted Excel file. Multi-provider key rotation and checkpointed
> runs so a long job survives a restart.

GUI-приложение для сбора базы компаний по нише и городу. Задаёшь «стоматологии,
Москва, 200 штук» — получаешь Excel с компаниями, сайтами, телефонами, реквизитами,
рейтингами и позициями в поиске.

## Зачем

Отдел продаж работает по спискам, которые кто-то собирает руками: открыть карты,
переписать названия, найти сайты, пробить телефоны, проверить, кто вообще жив.
День работы на сотню строк. Здесь то же самое делается за один запуск, а качество
выше — потому что данные сверяются между источниками, а не берутся из одного.

## Что делает

- **Discovery.** Поиск компаний по нише и городу через SERP-провайдеров
  (Serper, ValueSERP, SerpAPI, XMLRiver) — с ротацией ключей, чтобы не упираться
  в лимиты одного
- **Обогащение реквизитами.** ИНН, юрлицо, руководитель, официальные телефоны —
  из DaData и открытого реестра МСП
- **Рейтинги и позиции.** Оценки из картографических сервисов, позиции сайта
  в Google и Яндексе по целевому запросу
- **Нормализация.** Сопоставление названий из разных источников нечётким
  сравнением (`name_matcher.py`) — «ООО "Дента-Плюс"» и «Дента Плюс» это одна
  компания, а не две строки в базе
- **LLM-слой.** Модель добирает то, что не отдают API, и отбраковывает мусор —
  агрегаторы, каталоги, закрывшиеся точки. Реализовано на двух провайдерах:
  основной — Groq (быстрый и бесплатный), Gemini как запасной
- **Проверка контактов.** Сверка телефонов с сайтом компании, отсев подменных
  номеров коллтрекинга
- **Экспорт.** Excel с автофильтрами, статистикой и оформлением
- **Чекпойнты.** Долгий сбор пишет состояние на диск и продолжается с места
  обрыва, а не с нуля

## Стек

Python 3.11 · Tkinter · requests · Google Gemini API · Groq API · DaData API ·
openpyxl · PyInstaller

## Запуск

```bash
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # заполнить ключи провайдеров
python gui_app_serp.py
```

Сборка в исполняемый файл:

```bash
pyinstaller release.spec
```

## Структура

```
gui_app_serp.py        основное GUI (сбор через SERP-провайдеров)
gui_app.py             ранняя версия интерфейса
gui_release.py         сборка для распространения
collector_core_serp.py ядро сбора: discovery, оркестрация источников
collector_v5.py        предыдущее поколение коллектора
serp_rotator.py        ротация ключей и провайдеров поиска
dadata_enricher.py     обогащение реквизитами через DaData
enrich_registry.py     обогащение из реестра МСП
parse_msp.py           разбор выгрузки реестра
download_msp.py        загрузка реестра
rkn_enricher.py        дополнительные открытые источники
gemini_enricher.py     LLM-обогащение (Gemini)
groq_enricher.py       LLM-обогащение (Groq, основной провайдер)
gemini_filter.py       отбраковка нерелевантных результатов
groq_filter.py         то же на Groq
name_matcher.py        нечёткое сопоставление названий компаний
phone_site_check.py    сверка телефонов с сайтом
dir_phone_check.py     пакетная проверка телефонов
release.spec           конфигурация сборки PyInstaller
```

## О данных

В репозитории нет ни одной собранной базы — только код. Собранные данные
относятся к конкретным компаниям и включают контакты, поэтому в публичный
доступ не выкладываются. Сбор ведётся из открытых источников; ответственность
за дальнейшее использование результата лежит на том, кто запускает инструмент,
и регулируется законодательством о персональных данных и о рекламе.

## Лицензия

MIT
