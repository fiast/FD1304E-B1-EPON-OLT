# C-Data FD1304E-B1 EPON OLT — Zabbix template

Шаблон Zabbix для мониторинга EPON OLT **C-Data FD1304E-B1** (BDCOM-совместимый, enterprise OID
`.1.3.6.1.4.1.17409`) по SNMP: автообнаружение абонентских ONU и интерфейсов, оптические
параметры абонентов, теги для просмотра метрик одного абонента, готовые дашборды.

* Версия шаблона: **1.1** (Zabbix **7.4.x**, экспорт `version: '7.4'`)
* Протестировано на: C-Data FD1304E-B1, Zabbix 7.4.5

---

## Возможности

### Автообнаружение (LLD) абонентов (ONU)
* Имя абонента и статус (**Online / Offline**)
* **Оптические параметры**: Rx power (dBm), Tx power (dBm), напряжение (V), температура (°C),
  ток смещения лазера (mA), uptime ONU
* Оффлайн-ONU: оптические итемы остаются без данных (не становятся `unsupported`)
* Флаговые итемы online/offline на каждого ONU (основа для подсчёта по портам)

### Сводка по EPON-портам
* Отдельное LLD-правило по EPON-портам и calculated-итемы
  **`EPON port [<порт>] ONUs online`** / **`... Offline`** — сколько абонентов online/offline
  на каждом порту (считается внутри Zabbix, вендор такого счётчика не отдаёт)

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
| ONU items / triggers | `scope=onu`, `component=olt`, `subscriber=<имя ONU>`, `onu_id=<ONU id>`, `onu_port=<EPON порт>` |
| Interface items / triggers | `scope=port`, `component=olt`, `interface=<имя порта>`, `ifindex=<ifIndex>` |
| EPON port summary items | `scope=port`, `component=olt`, `interface=<имя порта>`, `ifindex=<ifIndex>` |

В **Monitoring → Latest data** включите колонку *Tags* и кликните по значению `subscriber=...`
(или `interface=...`) — увидите метрики только этого абонента/порта. В **Problems** клик по тегу
делает то же самое.

### Graph prototypes
* `ONU [{#SNMPVALUE}] optical signal` — Rx/Tx, dBm
* `Interface [{#SNMPVALUE}] traffic` — In/Out, bps
* `Interface [{#SNMPVALUE}] errors` — In/Out пакеты ошибок

Используются виджетом **Graph prototype** на дашбордах и доступны как обычные графики у итемов.

### Готовые дашборды
Статические дашборды создаются скриптом
[`dashboards/create_dashboards.py`](dashboards/create_dashboards.py):
* **Абонент** — метрики одного абонента (фильтр по тегу `subscriber`).
* **Абонентские интерфейсы (EPON)** — статус/ошибки/скорость портов, графики трафика и ошибок.
* **Подключения ONU** — сводка абонентских подключений: honeycomb-карта доступности
  Online/Offline, тепловая карта Rx, таблица подключений, графики сигналов.
* **Сводка по EPON-портам** — сколько ONU **online/offline на каждый EPON-порт**
  (таблица + honeycomb + график динамики).
* **All dashboards (Global view)** — общий дашборд-обзор: все проблемы OLT, таблица ONU
  (**имя/адрес + State, Rx, Tx, температура**), honeycomb доступности, карта уровней Rx,
  график Rx всех абонентов и сетка графиков сигнала по каждому абоненту.

### Дашборд на каждого абонента (автоматически)
Zabbix (7.4) **не имеет объекта «прототип дашборда»**, поэтому его роль выполняет скрипт
[`dashboards/sync_onu_dashboards.py`](dashboards/sync_onu_dashboards.py): он запускается по cron
и для каждого обнаруженного ONU создаёт/обновляет отдельный дашборд (название = адрес/имя ONU),
содержащий:
* **индикатор (gauge) Rx power** — последний уровень сигнала с цветовыми порогами;
* **индикатор (gauge) Tx power** — последний уровень;
* крупные значения: State, Temperature, Voltage, Bias current, Uptime;
* график сигнала **Rx/Tx (dBm)**;
* график мощности **Rx (dBm)** за 24 ч;
* проблемы только этого абонента (тег `subscriber`).

Пример структуры такого дашборда — [`dashboards/onu_dashboard_example.json`](dashboards/onu_dashboard_example.json).

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
Создаются пять публичных дашбордов:
* **`OLT <host> — Абонент (метрики одного абонента)`** — `Item navigator` со всеми метриками ONU
  (фильтр по тегу `subscriber`), `Problems` абонентов, сетка графиков Rx/Tx по каждому абоненту.
* **`OLT <host> — Абонентские интерфейсы (EPON)`** — таблица EPON-портов (статус, ошибки,
  скорость, трафик), проблемы портов, графики трафика и ошибок по каждому порту.
* **`OLT <host> — Подключения ONU (абоненты)`** — сводка абонентских подключений:
  * `Problems` только по ONU (`scope=onu`);
  * таблица подключений (`Item navigator`): статус, Rx/Tx, температура, напряжение, uptime;
  * **honeycomb «Доступность ONU»** — плитка Online/Offline на каждого абонента
    (зелёный = 1/Online, красный = 2/Offline);
  * **honeycomb «Карта Rx абонентов»** — тепловая карта уровня сигнала по абонентам
    (зелёный ≥ −24 dBm, жёлтый от −25 dBm, красный < −26 dBm);
  * сетка графиков «Сигнал ONU (Rx/Tx, dBm)» по каждому абоненту.
* **`OLT <host> — Сводка по EPON-портам (ONU online/offline)`** — сколько абонентов
  online/offline на каждом EPON-порту: таблица, два honeycomb (online/offline) и график
  динамики за 24 ч. Значения берутся из итемов
  `EPON port [<порт>] ONUs online` / `... OFFline` (calculated item, см. ниже).
* **`OLT <host> — All dashboards (Global view)`** — общий дашборд-обзор (рекомендуется
  как дашборд по умолчанию):
  * `Problems` — все проблемы OLT (тег `component=olt`);
  * `Item navigator` — таблица ONU: **имя (адрес) + State, Rx power, Tx power, Temperature**
    (4 шаблона итемов, фильтр по тегу `subscriber`/`onu_port` внутри виджета);
  * **honeycomb «Доступность ONU»** — имя ONU + Online/Offline;
  * **honeycomb «Карта уровней Rx»** — цветовая карта сигналов по абонентам;
  * **график «Rx всех абонентов»** — все ONU на одном графике (обзор деградаций);
  * **сетка графиков «Сигнал ONU (Rx/Tx)»** — по одному графику на абонента.

> Чтобы общий дашборд открывался сразу при входе: **User settings → Dashboard** и выбрать
> `OLT <host> — All dashboards (Global view)` (в Zabbix 7.x это персональная настройка пользователя).

> Honeycomb использует «плитку» на каждый найденный item (паттерн `ONU [*] ...` + тег
> `scope=onu`), поэтому новые абоненты появляются на карте автоматически после LLD.

### 5. (опционально) Дашборд на каждого абонента — автоматически

Zabbix **не имеет «прототипа дашборда»** (такого объекта нет ни в API, ни в UI: проверить можно
методом `dashboardprototype.get` — он вернёт «Method not found»). Роль прототипа выполняет скрипт
[`dashboards/sync_onu_dashboards.py`](dashboards/sync_onu_dashboards.py):

```bash
export ZABBIX_URL="https://zabbix.example.com/api_jsonrpc.php"
export ZABBIX_TOKEN="<API token>"
export ZABBIX_HOSTID="<host id>"            # или ZABBIX_TEMPLATEID для всех хостов шаблона
export ZABBIX_DASH_PREFIX="ONU"             # префикс имени дашборда

python3 dashboards/sync_onu_dashboards.py --dry-run      # посмотреть план
python3 dashboards/sync_onu_dashboards.py                # создать/обновить
python3 dashboards/sync_onu_dashboards.py --prune        # + удалить дашборды исчезнувших ONU
```

Скрипт идемпотентен: структура дашборда хешируется (файл `~/.cache/onu_dashboards.json`), при
отсутствии изменений обновление не выполняется. Пример cron (раз в 5 минут):

```cron
*/5 * * * * ZABBIX_URL="https://zabbix.example.com/api_jsonrpc.php" ZABBIX_TOKEN="<token>" \
  ZABBIX_HOSTID="<host id>" /usr/bin/python3 /opt/zabbix-onu-dashboards/sync_onu_dashboards.py \
  --prune >> /var/log/onu-dashboards.log 2>&1
```

Так «дашборд на каждого ONU» появляется сам после discovery и удаляется, когда ONU больше
не обнаружен.


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
   интерфейсы — `cdata.if.name`. Для сводки по портам есть отдельное правило `cdata.epon.lld`
   (тот же master, фильтр `{#SNMPVALUE}` по regex `^epon`).
3. **Item prototypes (dependent)** извлекают своё значение из JSON мастера.

### Подсчёт ONU online/offline по EPON-портам
Вендор не отдаёт по SNMP счётчик ONU на порт (таблицы `.1.3.6.1.4.1.17409.2.3.3.*` содержат
другие значения), поэтому счётчики считаются внутри Zabbix:

1. Для каждого ONU создаются флаговые итемы `cdata.onu.online[{#SNMPINDEX}]` / `...offline[...]`
   (1/0 по статусу ONU), и всем ONU-итемам добавляется тег `onu_port=<EPON порт>`.
2. Для каждого EPON-порта создаётся calculated item
   `EPON port [<порт>] ONUs online` с формулой (foreach-функции Zabbix 7.x):
   ```
   sum(last_foreach(//cdata.onu.online[*]?[tag="onu_port:epon 0/1/1"]))
   ```
   и аналогично `ONUs offline`.
3. Пустые порты (нет ONU) не становятся `unsupported` благодаря шагу предобработки
   **Check for not supported value** («Set value» = `0`).

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
dashboards/create_dashboards.py                   # 4 статических дашборда через API
dashboards/sync_onu_dashboards.py                 # «прототип дашборда»: дашборд на каждого ONU (cron)
dashboards/dashboards_structure.json              # дамп структуры статических дашбордов
dashboards/onu_dashboard_example.json             # пример сгенерированного дашборда абонента
tools/create_cdata_template.py                    # полный «сборщик» шаблона через API
tools/export_repo.py                              # экспорт шаблона / дамп дашбордов
docs/OID_reference.md                             # карта OID
```

## Другие OLT (BDCOM P3310B/C/D, Gateray GR-EP-OLT)

В репозитории — три шаблона, покрывающих используемый парк EPON OLT:

| OLT | Модель | Шаблон |
|---|---|---|
| `olt_snt1`, `olt_ulej7` | BDCOM P3310D / P3310C | **`C-Data_FD1304E-B1_EPON_OLT`** (та же вендорская MIB `17409`: ONU-имена, статус, Rx/Tx/темп./напряжение/ток, интерфейсы) |
| `olt_lenina2` | BDCOM P3310B (ПО 10.1.0B) | **`BDCOM_P3310B_EPON_OLT`** — прошивка **не отдаёт EPON MIB по SNMP**: мониторинг системных параметров и интерфейсов, включая логические интерфейсы ONU `EPON0/x:y` (статус абонента up/down, скорость, трафик bps, ошибки) |
| `olt_fedorenko10`, `olt_melio7` | Gateray GR-EP-OLT1-8 / GR-EP-OLT1-4 | **`Gateray_GR-EP-OLT_EPON_OLT`** — система (CPU, температура, alarm), интерфейсы (GE/PON), LLD ONU по MAC-таблице: имя (HEX→ASCII), статус (2=Offline, 3=Online), **Tx/Rx**, итоги Total ONUs online/offline |

Скрипты:
* [`tools/create_olt_templates.py`](tools/create_olt_templates.py) — создаёт шаблоны Gateray и BDCOM P3310B через API;
* создание хостов (SNMP-интерфейс + `{$SNMP_COMMUNITY}` + привязка шаблона) выполняйте в UI
  или своим скриптом — в репозиторий он не включён, т.к. содержит адреса и community;
* [`tools/check_all_olts.py`](tools/check_all_olts.py) — контроль сбора данных по всем OLT.

### Масштабирование оптики Gateray
`Rx/Tx` в вендорской MIB отдаются «сырыми» значениями. В шаблоне используются макросы:
`{$GATERAY.ONU.TX.SCALE}=0.01`, `{$GATERAY.ONU.RX.SCALE}=0.001`, `{$GATERAY.ONU.RX.OFFSET}=-30`
(`dBm = raw*SCALE + OFFSET`, значение `0` = «нет сигнала» отбрасывается, плюс проверка диапазона −60…10 dBm).
При расхождении с веб-интерфейсом OLT поправьте макросы.

### Если OLT отдаёт «only partial data received»
Для «слабых» OLT (BDCOM P3310C/D при большом числе ONU) помогает отключить combined/bulk-запросы
на SNMP-интерфейсе хоста: **Use combined requests = off**, `max_repetitions = 1`
(это же делает [`tools/postfix_olts.py`](tools/postfix_olts.py)).


## Благодарности / отказ от ответственности

Шаблон собран по фактическому анализу SNMP-дерева конкретного устройства (`snmpwalk` + проверка
на живом Zabbix). Названия/семантика вендорских OID могут отличаться между версиями ПО OLT —
проверяйте метрики в `Latest data`.

## Лицензия

MIT

