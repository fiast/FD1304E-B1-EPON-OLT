# C-Data FD1304E-B1 EPON OLT — Zabbix template

Шаблон Zabbix для мониторинга EPON OLT **C-Data FD1304E-B1** (BDCOM-совместимый, enterprise OID
`.1.3.6.1.4.1.17409`) по SNMP: автообнаружение абонентских ONU и интерфейсов, оптические
параметры абонентов, теги для просмотра метрик одного абонента, готовые дашборды.

* Версия шаблона: **1.0** (Zabbix **7.4.x**, экспорт `version: '7.4'`)
* Протестировано на: C-Data FD1304E-B1, Zabbix 7.4.5

---

## Возможности

### Автообнаружение (LLD) абонентов (ONU)
* Имя абонента и статус (**Online / Offline**)
* **Оптические параметры**: Rx power (dBm), Tx power (dBm), напряжение (V), температура (°C),
  ток смещения лазера (mA), uptime ONU
* Оффлайн-ONU: оптические итемы остаются без данных (не становятся `unsupported`)

### Автообнаружение (LLD) интерфейсов
* Admin / Oper status (с value map `up` / `down`)
* Speed (bps), входные/выходные октеты (B)
* Трафик **In/Out (bps)** (через `change per second` × 8)
* Пакеты ошибок In/Out

### Триггеры (прототипы)
| Триггер | Severity | Условие |
|---|---|---|
| `ONU [x] Rx power below {$CDATA.ONU.RX_MIN} dBm` | High | `last(rx) < -26` (восстановление `> -24`) |
| `ONU [x] offline` | Average | `last(state) = 2` |
| `ONU [x] optical data missing (offline/no signal)` | Warning | `nodata(rx,20m)` |
| `ONU [x] temperature above {$CDATA.ONU.TEMP_MAX} C` | Warning | `last(temp) > 60` |
| `ONU [x] Tx power out of range` | Warning | `last(tx) < 0 or > 5` |
| `[if] port is down` | Average | `admin=1 and oper=2` |
| `[if] input/output errors detected` | Warning | `change(errors) > {$CDATA.IF.ERRORS_WARN}` |

### Теги (просмотр одного абонента / порта)
| Объект | Теги |
|---|---|
| ONU items / triggers | `scope=onu`, `component=olt`, `subscriber=<имя ONU>`, `onu_id=<ONU id>` |
| Interface items / triggers | `scope=port`, `component=olt`, `interface=<имя порта>`, `ifindex=<ifIndex>` |

В **Monitoring → Latest data** включите колонку *Tags* и кликните по значению `subscriber=...`
(или `interface=...`) — увидите метрики только этого абонента/порта. В **Problems** клик по тегу
делает то же самое.

### Graph prototypes
* `ONU [{#SNMPVALUE}] optical signal` — Rx/Tx, dBm
* `Interface [{#SNMPVALUE}] traffic` — In/Out, bps
* `Interface [{#SNMPVALUE}] errors` — In/Out пакеты ошибок

Используются виджетом **Graph prototype** на дашбордах и доступны как обычные графики у итемов.

---

## Требования

* Zabbix Server/Proxy **7.4.x** (шаблон использует `walk[]` в SNMP OID и `SNMP_AGENT` итемы)
* SNMP v2c доступ к OLT (community), порт 161/udp
* Хост заведён в Zabbix с интерфейсом типа **SNMP**

## Установка

### 1. Импорт шаблона
`Data collection → Templates → Import` → файл
[`zabbix/template_C-Data_FD1304E-B1_EPON_OLT.yaml`](zabbix/template_C-Data_FD1304E-B1_EPON_OLT.yaml)
(правила импорта — по умолчанию: Create new / Update existing).

### 2. Создание хоста
1. `Data collection → Hosts → Create host`
2. Имя, группа (например `CDATA` / `Network devices`)
3. Добавьте интерфейс **SNMP**: IP OLT, порт `161`, SNMP version `v2c`, **SNMP community**
   (например `your-community`)
4. Макрос хоста `{$SNMP_COMMUNITY}` = ваше SNMP community
5. На вкладке *Templates* прилинкуйте **`C-Data FD1304E-B1 EPON OLT`**
6. Сохраните и подождите 1–2 минуты: в `Monitoring → Latest data` появятся итемы
   `ONU [...] ...` и `Interface [...] ...`

### 3. (опционально) Автосоздание/обновление через API
```bash
export ZABBIX_URL="https://zabbix.example.com/api_jsonrpc.php"
export ZABBIX_TOKEN="<API token>"        # Users → API tokens
export ZABBIX_HOSTID="<host id>"         # необязательно: прилинковать шаблон к хосту
python3 tools/create_cdata_template.py
```

### 4. (опционально) Дашборды
Zabbix 7.4 **не экспортирует дашборды** через `configuration.export`, поэтому они создаются
скриптом:
```bash
export ZABBIX_URL="https://zabbix.example.com/api_jsonrpc.php"
export ZABBIX_TOKEN="<API token>"
export ZABBIX_HOSTID="<host id>"
export ZABBIX_TEMPLATEID="<template id>"
export ZABBIX_DASH_PREFIX="OLT"
python3 dashboards/create_dashboards.py
```
Создаются два публичных дашборда:
* **`OLT <host> — Абонент (метрики одного абонента)`** — `Item navigator` со всеми метриками ONU
  (фильтр по тегу `subscriber`), `Problems` абонентов, сетка графиков Rx/Tx по каждому абоненту.
* **`OLT <host> — Абонентские интерфейсы (EPON)`** — таблица EPON-портов (статус, ошибки,
  скорость, трафик), проблемы портов, графики трафика и ошибок по каждому порту.

---

## Макросы

| Макрос | По умолчанию | Описание |
|---|---|---|
| `{$SNMP_COMMUNITY}` | — | SNMP community (задаётся на хосте) |
| `{$CDATA.ONU.RX_MIN}` | `-26` | Порог срабатывания «низкий Rx» ONU, dBm |
| `{$CDATA.ONU.RX_OK}` | `-24` | Порог восстановления «низкий Rx», dBm |
| `{$CDATA.ONU.TEMP_MAX}` | `60` | Максимальная температура ONU, °C |
| `{$CDATA.IF.ERRORS_WARN}` | `1` | Порог прироста ошибок на интерфейсе |

## Что опрашивается (ключевые OID)

| Метрика | OID (таблица) | Индекс |
|---|---|---|
| Имя ONU | `.1.3.6.1.4.1.17409.2.3.4.1.1.2` | `ONU_ID` |
| Статус ONU (1=online, 2=offline) | `.1.3.6.1.4.1.17409.2.3.4.1.1.8` | `ONU_ID` |
| Uptime ONU | `.1.3.6.1.4.1.17409.2.3.4.1.1.18` | `ONU_ID` |
| Rx power ONU (0.01 dBm) | `.1.3.6.1.4.1.17409.2.3.4.2.1.4` | `ONU_ID.1.<port>` |
| Tx power ONU (0.01 dBm) | `.1.3.6.1.4.1.17409.2.3.4.2.1.5` | `ONU_ID.1.<port>` |
| Напряжение ONU (mV) | `.1.3.6.1.4.1.17409.2.3.4.2.1.6` | `ONU_ID.1.<port>` |
| Температура ONU (0.0001 °C) | `.1.3.6.1.4.1.17409.2.3.4.2.1.7` | `ONU_ID.1.<port>` |
| Ток смещения ONU (µA) | `.1.3.6.1.4.1.17409.2.3.4.2.1.8` | `ONU_ID.1.<port>` |
| ifDescr / ifAdminStatus / ifOperStatus | `.1.3.6.1.2.1.2.2.1.{2,7,8}` | `ifIndex` |
| ifSpeed / ifInOctets / ifOutOctets | `.1.3.6.1.2.1.2.2.1.{5,10,16}` | `ifIndex` |
| ifInErrors / ifOutErrors | `.1.3.6.1.2.1.2.2.1.{14,20}` | `ifIndex` |

Подробная карта OID — [`docs/OID_reference.md`](docs/OID_reference.md).

## Масштабирование значений

| Метрика | Как считается | Пример |
|---|---|---|
| Rx / Tx power | JSON `val` × `0.01` → dBm | `-2114` → `-21.14 dBm` |
| Напряжение | × `0.001` → V | `1215` → `1.215 V` |
| Температура | × `0.0001` → °C | `332000` → `33.2 °C` |
| Ток смещения | × `0.001` → mA | `2725` → `2.725 mA` |
| Трафик | `change per second` × `8` → bps | октеты → биты/с |

## Как это устроено (важно для поддержки)

1. **Master-итемы** используют SNMP OID вида `walk[<oid>]` (асинхронный SNMP walk, Zabbix 7.x)
   и JavaScript-предобработку, которая превращает «сырой» вывод snmpwalk в JSON-массив
   `[{"idx":"...","val":"..."}]`.
2. **LLD-правила (dependent items)** навешены на master «имена»: ONU — `cdata.onu.name`,
   интерфейсы — `cdata.if.name`.
3. **Item prototypes (dependent)** извлекают своё значение из JSON мастера.

### Почему извлечение сделано на JavaScript, а не JSONPath
На Zabbix **7.4.5** LLD-макрос `{#SNMPINDEX}` внутри параметров предобработки подставляется
как `#<value>` (лишний `#` сохраняется от имени макроса), из-за чего фильтр JSONPath не находит
значение. Поэтому в прототипах используется JavaScript:
```js
var id = "{#SNMPINDEX}".replace(/^#/, "");
var data = JSON.parse(value);
for (var i = 0; i < data.length; i++) {
    if (data[i].idx === id) { return data[i].val; }
}
return "";
```
и следующий шаг **Matches regular expression** с обработкой ошибки «Discard value», чтобы
оффлайн-ONU не становились `unsupported`.

Если вы предпочитаете JSONPath — рабочий вариант (обязателен `.first()`):
`$.[?(@.idx=="#{#SNMPINDEX}")].val.first()`

## Известные особенности

* Триггер `[if] port is down` срабатывает для **всех** портов с `admin=up` и `oper=down`,
  включая свободные (неподключённые) порты. Если это шумно — отключите триггер-прототип или
  переведите неиспользуемые порты в admin-down.
* Масштаб температуры (0.0001 °C), напряжения и тока подобраны эмпирически; при сомнениях
  сверьте с веб-интерфейсом OLT и при необходимости поправьте множитель.
* Некоторые таблицы вендора (например `.1.3.6.1.4.1.17409.2.3.3.5`) отдают значения,
  интерпретация которых не подтверждена, поэтому в шаблон они не включены.

## Структура репозитория

```
zabbix/template_C-Data_FD1304E-B1_EPON_OLT.yaml   # импортируемый шаблон
dashboards/create_dashboards.py                   # создание дашбордов через API
dashboards/dashboards_structure.json              # дамп структуры дашбордов (reference)
tools/create_cdata_template.py                    # полный «сборщик» шаблона через API
tools/export_repo.py                              # экспорт шаблона / дамп дашбордов
docs/OID_reference.md                             # карта OID
```

## Благодарности / отказ от ответственности

Шаблон собран по фактическому анализу SNMP-дерева конкретного устройства (`snmpwalk` + проверка
на живом Zabbix). Названия/семантика вендорских OID могут отличаться между версиями ПО OLT —
проверяйте метрики в `Latest data`.

## Лицензия

MIT

