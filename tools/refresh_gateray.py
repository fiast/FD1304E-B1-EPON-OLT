#!/usr/bin/env python3
"""Drop stale Gateray (gas.*) discovered data on hosts so the LLD re-creates it correctly.

Usage: python3 refresh_gateray.py [hostname ...]   (default: all hosts with the Gateray template)
"""
import json, os, ssl, sys, urllib.request

URL = os.environ["ZABBIX_URL"]; TOKEN = os.environ["ZABBIX_TOKEN"]
PREFIX = "gas."


def api(m, p):
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    d = json.dumps({"jsonrpc": "2.0", "method": m, "params": p, "id": 1}).encode()
    r = urllib.request.Request(URL, data=d,
        headers={"Content-Type": "application/json-rpc", "Authorization": "Bearer " + TOKEN}, method="POST")
    res = json.loads(urllib.request.urlopen(r, context=ctx, timeout=60).read())
    if "error" in res:
        print("ERR", m, res["error"]); return []
    return res.get("result") or []


hosts = api("host.get", {"output": ["hostid", "host"], "selectParentTemplates": ["templateid", "host"]})
if len(sys.argv) > 1:
    hosts = [h for h in hosts if h["host"] in sys.argv[1:]]
else:
    hosts = [h for h in hosts
             if any(t["host"] == "Gateray_GR-EP-OLT_EPON_OLT" for t in h.get("parentTemplates", []))]
for h in hosts:
    items = api("item.get", {"output": ["itemid", "key_"], "hostids": h["hostid"]})
    n = 0
    for i in items:
        if i["key_"].startswith(PREFIX):
            api("item.delete", [i["itemid"]])
            n += 1
    print(f"{h['host']}: deleted {n} discovered items (prefix {PREFIX}); LLD will recreate them")
