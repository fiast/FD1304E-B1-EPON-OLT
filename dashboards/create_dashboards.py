#!/usr/bin/env python3
"""Create Zabbix dashboards for the C-Data OLT (subscriber signals + subscriber interfaces)."""
import json, ssl, urllib.request, os

URL = os.environ.get("ZABBIX_URL", "https://zabbix.example.com/api_jsonrpc.php")
TOKEN = os.environ.get("ZABBIX_TOKEN", "")
HOST = os.environ.get("ZABBIX_HOSTID", "")      # host id the dashboards are built for
TPL = os.environ.get("ZABBIX_TEMPLATEID", "")   # template that holds the graph prototypes
DASH_PREFIX = os.environ.get("ZABBIX_DASH_PREFIX", "OLT")

# positions/sizes are in 72-col grid units
UNITS = 24


def api(m, p):
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    d = json.dumps({"jsonrpc": "2.0", "method": m, "params": p, "id": 1}).encode()
    r = urllib.request.Request(URL, data=d,
        headers={"Content-Type": "application/json-rpc", "Authorization": "Bearer " + TOKEN}, method="POST")
    res = json.loads(urllib.request.urlopen(r, context=ctx, timeout=60).read())
    if "error" in res:
        print("  ERR", m, json.dumps(res["error"], ensure_ascii=False)); return None
    return res.get("result")


def f(t, name, value):
    return {"type": str(t), "name": name, "value": str(value)}


def tags_field(prefix, tag, operator, value=""):
    return [f(1, f"{prefix}.0.tag", tag), f(0, f"{prefix}.0.operator", operator), f(1, f"{prefix}.0.value", value)]


def graph_proto_id(name):
    r = api("graphprototype.get", {"templateids": TPL, "filter": {"name": name}, "output": ["graphid"]})
    return r[0]["graphid"] if r else None


def delete_dashboard(name):
    r = api("dashboard.get", {"output": ["dashboardid"], "filter": {"name": name}})
    if r:
        api("dashboard.delete", [r[0]["dashboardid"]])
        print("  deleted previous dashboard:", name)


def problems_widget(x, y, w, h, name, tag, operator=1, value="", lines=20):
    fields = [f(3, "hostids.0", HOST)]
    fields += tags_field("tags", tag, operator, value)
    fields += [f(0, "evaltype", 0), f(0, "show_tags", 3), f(0, "show_suppressed", 1),
               f(0, "sort_triggers", 3), f(0, "show_lines", lines)]
    return {"type": "problems", "name": name, "x": str(x), "y": str(y), "width": str(w),
            "height": str(h), "fields": fields}


def itemnav_widget(x, y, w, h, name, item_pattern, tag, operator=1, value="", lines=50):
    patterns = [item_pattern] if isinstance(item_pattern, str) else list(item_pattern)
    fields = [f(3, "hostids.0", HOST)]
    for i, p in enumerate(patterns):
        fields.append(f(1, f"items.{i}", p))
    fields += tags_field("item_tags", tag, operator, value)
    fields += [f(0, "state", 0), f(0, "problems", 1), f(0, "show_lines", lines)]
    return {"type": "itemnavigator", "name": name, "x": str(x), "y": str(y), "width": str(w),
            "height": str(h), "fields": fields}


def graphproto_widget(x, y, w, h, name, gpid, columns=2, rows=2):
    fields = [f(0, "source_type", 0), f(7, "graphid.0", gpid), f(0, "columns", columns), f(0, "rows", rows),
              f(0, "show_legend", 1), f(1, "time_period.from", "now-3h"), f(1, "time_period.to", "now")]
    return {"type": "graphprototype", "name": name, "x": str(x), "y": str(y), "width": str(w),
            "height": str(h), "fields": fields}


def svggraph_widget(x, y, w, h, name, datasets, from_="now-6h"):
    fields = []
    for i, (host, item, color) in enumerate(datasets):
        fields += [f(1, f"ds.{i}.hosts.0", host), f(1, f"ds.{i}.items.0", item), f(1, f"ds.{i}.color", color)]
    fields += [f(0, "legend_statistic", 1), f(0, "legend_lines", 2),
               f(0, "righty", 0), f(1, "time_period.from", from_), f(1, "time_period.to", "now")]
    return {"type": "svggraph", "name": name, "x": str(x), "y": str(y), "width": str(w),
            "height": str(h), "fields": fields}


def honeycomb_widget(x, y, w, h, name, item_pattern, tag, operator, value, thresholds,
                     primary_label="{ITEM.NAME}", primary_size=0, secondary_value=True):
    """Honeycomb (availability/heat map). thresholds = [(numeric_threshold, 'RRGGBB'), ...] ascending."""
    fields = [f(3, "hostids.0", HOST), f(1, "items.0", item_pattern)]
    fields += tags_field("item_tags", tag, operator, value)
    fields += [f(0, "show.0", 1), f(0, "show.1", 2),
               f(0, "primary_label_type", 0), f(1, "primary_label", primary_label),
               f(0, "primary_label_decimal_places", 0),
               f(0, "primary_label_size_type", 0), f(0, "primary_label_size", primary_size or 20),
               f(0, "secondary_label_type", 1 if secondary_value else 0),
               f(0, "secondary_label_size_type", 0), f(0, "secondary_label_size", 30),
               f(0, "secondary_label_decimal_places", 2),
               f(0, "maintenance", 0)]
    if not secondary_value:
        fields += [f(1, "secondary_label", "{ITEM.NAME}")]
    for i, (thr, color) in enumerate(thresholds):
        fields += [f(1, f"thresholds.{i}.color", color), f(1, f"thresholds.{i}.threshold", str(thr))]
    return {"type": "honeycomb", "name": name, "x": str(x), "y": str(y), "width": str(w),
            "height": str(h), "fields": fields}


def create(name, pages):
    delete_dashboard(name)
    r = api("dashboard.create", {"name": name, "display_period": "30", "auto_start": "1",
                                 "private": 0, "pages": pages})
    print(f"  created dashboard {name!r}: {r}")
    return r


def main():
    g_signal = graph_proto_id("ONU [{#SNMPVALUE}] optical signal")
    g_traffic = graph_proto_id("Interface [{#SNMPVALUE}] traffic")
    g_errors = graph_proto_id("Interface [{#SNMPVALUE}] errors")
    print("graph prototype ids:", g_signal, g_traffic, g_errors)

    hostname = api("host.get", {"hostids": HOST, "output": ["host"]})[0]["host"]
    pre = f"{DASH_PREFIX} {hostname} — "

    # ---------- Dashboard 1: single subscriber + all signals ----------
    print("\n=== Dashboard: subscriber (single) ===")
    create(pre + "Абонент (метрики одного абонента)", [{
        "name": "Абонент",
        "widgets": [
            itemnav_widget(0, 0, 44, 10,
                           "Метрики абонента: в фильтре тегов укажите subscriber = <имя абонента>",
                           "ONU [*", "subscriber", 4, "", 100),
            problems_widget(44, 0, 28, 10, "Проблемы абонентов (клик по тегу = один абонент)",
                            "subscriber", 4, "", 25),
            graphproto_widget(0, 10, 72, 16, "Сигнал ONU (Rx/Tx, dBm) — по одному графику на абонента",
                              g_signal, columns=3, rows=3),
        ]}])

    # ---------- Dashboard 2: subscriber interfaces ----------
    print("\n=== Dashboard: subscriber interfaces ===")
    create(pre + "Абонентские интерфейсы (EPON)", [{
        "name": "Абонентские интерфейсы",
        "widgets": [
            itemnav_widget(0, 0, 44, 10,
                           "EPON порты: статус, ошибки, скорость (в фильтре тегов: interface = <имя>)",
                           "Interface [epon*", "scope", 1, "port", 100),
            problems_widget(44, 0, 28, 10, "Проблемы портов (scope=port)", "scope", 1, "port", 25),
            graphproto_widget(0, 10, 72, 14, "Трафик интерфейсов (bps)", g_traffic, columns=3, rows=2),
            graphproto_widget(0, 24, 72, 14, "Ошибки интерфейсов (пакеты)", g_errors, columns=3, rows=2),
        ]}])

    # ---------- Dashboard 3: ONU subscriber connections ----------
    print("\n=== Dashboard: ONU subscriber connections ===")
    create(pre + "Подключения ONU (абоненты)", [{
        "name": "Подключения ONU",
        "widgets": [
            problems_widget(0, 0, 30, 9, "Проблемы абонентских подключений (scope=onu)",
                            "scope", 1, "onu", 25),
            itemnav_widget(30, 0, 42, 9,
                           "Подключения ONU: статус, сигналы, uptime (фильтр: subscriber = <имя>)",
                           "ONU [*", "subscriber", 4, "", 100),
            honeycomb_widget(0, 9, 36, 12, "Доступность ONU (Online / Offline)",
                             "ONU [*] State", "scope", 1, "onu",
                             [(1, "4CAF50"), (2, "E65660")]),
            honeycomb_widget(36, 9, 36, 12, "Карта Rx абонентов, dBm (красный < -26)",
                             "ONU [*] Rx power", "scope", 1, "onu",
                             [(-26, "E65660"), (-25, "FCCB1D"), (-24, "4CAF50")]),
            graphproto_widget(0, 21, 72, 14, "Сигнал ONU (Rx/Tx, dBm) по каждому абоненту",
                              g_signal, columns=3, rows=2),
        ]}])

    # ---------- Dashboard 4: EPON port ONU summary ----------
    print("\n=== Dashboard: EPON port summary ===")
    create(pre + "Сводка по EPON-портам (ONU online/offline)", [{
        "name": "Сводка по EPON-портам",
        "widgets": [
            itemnav_widget(0, 0, 72, 10,
                           "Сводка по EPON-портам: ONUs online / offline",
                           "EPON port [*", "scope", 1, "port", 100),
            honeycomb_widget(0, 10, 36, 10, "ONU online по EPON-портам",
                             "EPON port [*] ONUs online", "scope", 1, "port",
                             [(0, "E65660"), (1, "4CAF50")]),
            honeycomb_widget(36, 10, 36, 10, "ONU offline по EPON-портам",
                             "EPON port [*] ONUs offline", "scope", 1, "port",
                             [(0, "4CAF50"), (1, "E65660")]),
            svggraph_widget(0, 20, 72, 12, "ONU online/offline по EPON-портам (динамика)",
                            [(hostname, "EPON port [*] ONUs online", "4CAF50"),
                             (hostname, "EPON port [*] ONUs offline", "E65660")], from_="now-24h"),
            problems_widget(0, 32, 72, 8, "Проблемы портов (scope=port)", "scope", 1, "port", 25),
        ]}])

    # ---------- Dashboard 5: All dashboards / Global view (ONU overview) ----------
    print("\n=== Dashboard: All dashboards (Global view) ===")
    create(pre + "All dashboards (Global view)", [{
        "name": "ONU: имена, сигналы, статусы",
        "widgets": [
            problems_widget(0, 0, 72, 8, "Все проблемы OLT (component=olt)", "component", 1, "olt", 30),
            itemnav_widget(0, 8, 72, 14,
                           "ONU: имя (адрес) + сигналы — фильтр по тегу subscriber / onu_port",
                           ["ONU [*] State", "ONU [*] Rx power", "ONU [*] Tx power", "ONU [*] Temperature"],
                           "scope", 1, "onu", 300),
            honeycomb_widget(0, 22, 36, 12, "Доступность ONU (имя / Online-Offline)",
                             "ONU [*] State", "scope", 1, "onu",
                             [(1, "4CAF50"), (2, "E65660")]),
            honeycomb_widget(36, 22, 36, 12, "Карта уровней Rx, dBm (красный < -26)",
                             "ONU [*] Rx power", "scope", 1, "onu",
                             [(-26, "E65660"), (-25, "FCCB1D"), (-24, "4CAF50")]),
            svggraph_widget(0, 34, 72, 12, "Rx всех абонентов, dBm (обзор)",
                            [(hostname, "ONU [*] Rx power", "1E90FF")], from_="now-6h"),
            graphproto_widget(0, 46, 72, 16, "Сигнал ONU (Rx/Tx, dBm) по каждому абоненту",
                              g_signal, columns=3, rows=3),
        ]}])



if __name__ == "__main__":
    main()
