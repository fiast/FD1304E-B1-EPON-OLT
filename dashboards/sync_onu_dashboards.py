#!/usr/bin/env python3
"""Create/update one Zabbix dashboard per discovered ONU (subscriber).

Zabbix (7.4) has NO native "dashboard prototype" object, so this script plays that role:
run it periodically (cron / systemd timer) and every discovered ONU gets its own
dashboard named after the subscriber (the ONU name, e.g. "epon 0/1/1 onu 1 lenina205-xleb").

Dashboard contents (readable at a glance):
  * gauge    - Rx power, last level (with thresholds)
  * gauge    - Tx power, last level
  * item     - State / Temperature / Voltage / Bias current / Uptime (last value)
  * graph    - Rx/Tx optical signal (dBm) over time
  * graph    - Rx power (dBm) over time
  * problems - ONU problems (tag subscriber=<name>)

Env:
  ZABBIX_URL, ZABBIX_TOKEN            - required
  ZABBIX_HOSTID                       - optional; default: all hosts linked to the template
  ZABBIX_TEMPLATEID                   - used to find hosts when HOSTID is not set
  ZABBIX_DASH_PREFIX                  - dashboard name prefix (default "ONU")
Options:
  --prune        delete dashboards of ONUs that are no longer discovered
  --state FILE   fingerprint cache (default: ~/.cache/onu_dashboards.json)
  --dry-run      print what would be done
"""
import argparse, hashlib, json, os, ssl, re, sys, urllib.request

URL = os.environ.get("ZABBIX_URL", "https://zabbix.example.com/api_jsonrpc.php")
TOKEN = os.environ.get("ZABBIX_TOKEN", "")
HOST_ID = os.environ.get("ZABBIX_HOSTID", "")
TPL_ID = os.environ.get("ZABBIX_TEMPLATEID", "")
DASH_PREFIX = os.environ.get("ZABBIX_DASH_PREFIX", "ONU")
STATE_DEFAULT = os.path.expanduser("~/.cache/onu_dashboards.json")

METRICS = ("State", "Rx power", "Tx power", "Voltage", "Temperature", "Bias current", "Uptime")


def api(method, params):
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    data = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(URL, data=data,
        headers={"Content-Type": "application/json-rpc", "Authorization": f"Bearer {TOKEN}"}, method="POST")
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        res = json.loads(r.read())
    if "error" in res:
        raise RuntimeError(f"{method}: {json.dumps(res['error'], ensure_ascii=False)}")
    return res.get("result")


def f(t, name, value):
    return {"type": str(t), "name": name, "value": str(value)}


def widget(w, x, y, width, height):
    return dict(w, x=str(x), y=str(y), width=str(width), height=str(height))


def gauge(itemid, desc, vmin, vmax, thresholds, title=""):
    fields = [f(4, "itemid.0", itemid), f(0, "angle", 180), f(0, "min", vmin), f(0, "max", vmax),
              f(0, "show.0", 1), f(0, "show.1", 2), f(0, "show.2", 4), f(0, "show.3", 5),
              f(1, "description", desc), f(0, "desc_size", 15), f(0, "desc_bold", 1),
              f(0, "value_size", 35), f(0, "units_show", 1),
              f(0, "decimal_places", 2), f(0, "units_size", 20)]
    for i, (thr, color) in enumerate(thresholds):
        fields += [f(1, f"thresholds.{i}.color", color), f(1, f"thresholds.{i}.threshold", str(thr))]
    return {"type": "gauge", "name": title, "fields": fields}


def item_value(itemid, desc, title=""):
    return {"type": "item", "name": title, "fields": [
        f(4, "itemid.0", itemid), f(0, "show.0", 1), f(0, "show.1", 2), f(0, "show.2", 3),
        f(0, "show.3", 4), f(1, "description", desc), f(0, "desc_size", 20), f(0, "desc_bold", 1),
        f(0, "value_size", 40), f(0, "units_show", 1), f(0, "decimal_places", 2)]}


def svggraph(hostname, items, name, from_):
    fields = [f(0, "legend_statistic", 1), f(0, "legend_lines", 2), f(0, "righty", 0),
              f(1, "time_period.from", from_), f(1, "time_period.to", "now")]
    for i, it in enumerate(items):
        fields += [f(1, f"ds.0.hosts.{i}", hostname), f(1, f"ds.0.items.{i}", it)]
    return {"type": "svggraph", "name": name, "fields": fields}


def problems_widget(hostid, onu_name):
    return {"type": "problems", "name": "Проблемы абонента", "fields": [
        f(3, "hostids.0", hostid), f(1, "tags.0.tag", "subscriber"), f(0, "tags.0.operator", 1),
        f(1, "tags.0.value", onu_name), f(0, "evaltype", 0), f(0, "show_tags", 3),
        f(0, "sort_triggers", 3), f(0, "show_lines", 10)]}


def build_dashboard(hostid, hostname, onu_name, items):
    """items: {'State': itemid, 'Rx power': itemid, ...}"""
    widgets = [
        widget(gauge(items.get("Rx power"), "Rx power, dBm", -35, 0,
                     [(-26, "E65660"), (-25, "FCCB1D"), (-24, "4CAF50")],
                     "Уровень сигнала Rx (последний, dBm)"), 0, 0, 24, 9),
        widget(gauge(items.get("Tx power"), "Tx power, dBm", 0, 5,
                     [(1, "FCCB1D"), (2, "4CAF50")],
                     "Уровень сигнала Tx (последний, dBm)"), 24, 0, 24, 9),
        widget(item_value(items.get("State"), "State (1=Online / 2=Offline)", "Состояние ONU"), 48, 0, 24, 9),
        widget(svggraph(hostname, [f"ONU [{onu_name}] Rx power", f"ONU [{onu_name}] Tx power"],
                        "Сигнал ONU (Rx/Tx, dBm)", "now-6h"), 0, 9, 72, 12),
        widget(svggraph(hostname, [f"ONU [{onu_name}] Rx power"],
                        "Мощность сигнала Rx, dBm", "now-24h"), 0, 21, 72, 12),
        widget(item_value(items.get("Temperature"), "Temperature, C", "Температура"), 0, 33, 18, 5),
        widget(item_value(items.get("Voltage"), "Voltage, V", "Напряжение"), 18, 33, 18, 5),
        widget(item_value(items.get("Bias current"), "Bias current, mA", "Ток смещения"), 36, 33, 18, 5),
        widget(item_value(items.get("Uptime"), "Uptime", "Uptime ONU"), 54, 33, 18, 5),
        widget(problems_widget(hostid, onu_name), 0, 38, 72, 8),
    ]
    return [{"name": "Абонент", "widgets": widgets}]


def collect_onus(hostid):
    """Return {hostid: (hostname, {onu_name: {metric: itemid}})}."""
    out = {}
    if hostid:
        hosts = api("host.get", {"hostids": hostid, "output": ["hostid", "host"]})
    elif TPL_ID:
        hosts = api("host.get", {"templateids": TPL_ID, "output": ["hostid", "host"]})
    else:
        sys.exit("set ZABBIX_HOSTID or ZABBIX_TEMPLATEID")
    for h in hosts:
        data = {}
        for it in api("item.get", {"hostids": h["hostid"], "output": ["itemid", "name"],
                                   "search": {"key_": "cdata.onu."}}):
            m = re.match(r"^ONU \[(.+)\] (.+)$", it["name"])
            if m and m.group(2) in METRICS:
                data.setdefault(m.group(1), {})[m.group(2)] = it["itemid"]
        out[h["hostid"]] = (h["host"], data)
    return out


def load_state(path):
    try:
        return json.load(open(path))
    except Exception:
        return {}


def save_state(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(state, open(path, "w"), indent=1)


def upsert_dashboard(dash_name, pages, st, dry_run):
    fp = hashlib.sha1(json.dumps(pages, sort_keys=True).encode()).hexdigest()
    if st.get("fp") == fp and st.get("dashboardid"):
        print(f"  = {dash_name} (unchanged)")
        return st
    if dry_run:
        print(f"  would {'update' if st.get('dashboardid') else 'create'} {dash_name}")
        return st
    did = st.get("dashboardid")
    if did and not api("dashboard.get", {"dashboardids": did, "output": ["dashboardid"]}):
        did = None
    if not did:
        ex = api("dashboard.get", {"output": ["dashboardid"], "filter": {"name": dash_name}})
        did = ex[0]["dashboardid"] if ex else None
    if did:
        api("dashboard.update", {"dashboardid": did, "pages": pages})
        print(f"  ~ {dash_name} (updated)")
    else:
        did = api("dashboard.create", {"name": dash_name, "display_period": "30", "auto_start": "1",
                                       "private": 0, "pages": pages})["dashboardids"][0]
        print(f"  + {dash_name} (created id={did})")
    return {"dashboardid": did, "fp": fp}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prune", action="store_true", help="delete dashboards of removed ONUs")
    ap.add_argument("--state", default=STATE_DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not TOKEN:
        sys.exit("ZABBIX_TOKEN is not set")

    state = load_state(args.state)
    seen = set()
    total = 0
    for hostid, (hostname, onus) in sorted(collect_onus(HOST_ID).items()):
        print(f"host {hostname} ({hostid}): {len(onus)} ONU discovered")
        total += len(onus)
        for onu_name in sorted(onus):
            dash_name = f"{DASH_PREFIX} {onu_name}"
            seen.add(dash_name)
            pages = build_dashboard(hostid, hostname, onu_name, onus[onu_name])
            st = upsert_dashboard(dash_name, pages, state.get(dash_name, {}), args.dry_run)
            if not args.dry_run:
                state[dash_name] = st
    print(f"total ONU dashboards: {total}")

    if args.prune:
        for d in api("dashboard.get", {"output": ["dashboardid", "name"]}):
            if d["name"].startswith(DASH_PREFIX + " ") and d["name"] not in seen:
                if args.dry_run:
                    print(f"  would delete {d['name']}")
                else:
                    api("dashboard.delete", [d["dashboardid"]])
                    state.pop(d["name"], None)
                    print(f"  - {d['name']} (deleted: ONU not discovered anymore)")

    if not args.dry_run:
        save_state(args.state, state)


if __name__ == "__main__":
    main()

