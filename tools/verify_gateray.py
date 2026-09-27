#!/usr/bin/env python3
"""Verify Gateray ONU values (Rx/Tx/name/temp/volt/bias) against the reference NMS table.

Usage: python3 verify_gateray.py <host> [pon_filter]
"""
import json, os, ssl, sys, urllib.request

URL = os.environ["ZABBIX_URL"]; TOKEN = os.environ["ZABBIX_TOKEN"]


def api(m, p):
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    d = json.dumps({"jsonrpc": "2.0", "method": m, "params": p, "id": 1}).encode()
    r = urllib.request.Request(URL, data=d,
        headers={"Content-Type": "application/json-rpc", "Authorization": "Bearer " + TOKEN}, method="POST")
    res = json.loads(urllib.request.urlopen(r, context=ctx, timeout=60).read())
    if "error" in res:
        print("ERR", m, res["error"]); return []
    return res.get("result") or []


host = sys.argv[1]
h = api("host.get", {"output": ["hostid"], "filter": {"host": host}})[0]["hostid"]
items = api("item.get", {"output": ["key_", "name", "lastvalue", "state", "error"],
                         "hostids": h, "search": {"key_": "gas.onu."},
                         "selectItemDiscovery": ["parent_itemid"]})
rows = {}
for i in items:
    if not i["key_"].endswith("]") or "[" not in i["key_"]:
        continue
    base, idx = i["key_"].split("[")[0], i["key_"][i["key_"].index("[") + 1:-1]
    rows.setdefault(idx, {})[base] = (i["lastvalue"], i["state"], i["error"], i["name"])
print(f"host={host} ONU indexes with data: {len(rows)}")
print(f"{'PON/ONU':>8} {'MAC (from item name)':<50} {'Name':<12} {'St':>3} {'Rx dBm':>8} {'Tx dBm':>8} "
      f"{'V':>7} {'mA':>6} {'C':>9} {'dist':>6}")
for idx in sorted(rows, key=lambda s: tuple(int(x) for x in s.split("_"))):
    r = rows[idx]
    if sys.argv[2:] and idx.split("_")[0] not in sys.argv[2:]:
        continue
    def g(k):
        v = r.get(k, ("", 0, "", ""))
        return v[0]
    mac = ""
    nm = r.get("gas.onu.rx", ("", 0, "", ""))[3]
    if "] " in nm:
        mac = nm.split("] ")[1].replace(" Rx power", "")
    print(f"{idx:>8} {mac:<50} {g('gas.onu.name'):<12} {g('gas.onu.state'):>3} "
          f"{g('gas.onu.rx'):>8} {g('gas.onu.tx'):>8} {g('gas.onu.volt'):>7} {g('gas.onu.bias'):>6} "
          f"{g('gas.onu.temp'):>9} {g('gas.onu.dist'):>6}")
bad = [(i, k, v) for i, r in rows.items() for k, v in r.items() if v[1] == 1]
for i, k, v in bad[:10]:
    print(f"  ! {k}[{i}] {v[2][:90]}")
print(f"unsupported items: {len(bad)}")
