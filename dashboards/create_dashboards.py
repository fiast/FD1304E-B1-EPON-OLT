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
    fields = [f(3, "hostids.0", HOST), f(1, "items.0", item_pattern)]
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


if __name__ == "__main__":
    main()
