#!/usr/bin/env python3
"""Export the CDATA template to YAML and dump the OLT dashboards to JSON (reference).

Note: Zabbix 7.4 configuration.export does not support dashboards, so dashboards are
recreated with dashboards/create_dashboards.py; their structure is dumped here as JSON.

Env: ZABBIX_URL, ZABBIX_TOKEN, ZABBIX_TEMPLATEID, REPO_DIR
"""
import json, ssl, urllib.request, os

URL = os.environ.get("ZABBIX_URL", "https://zabbix.example.com/api_jsonrpc.php")
TOKEN = os.environ.get("ZABBIX_TOKEN", "")
TPL = os.environ.get("ZABBIX_TEMPLATEID", "")
OUT = os.environ.get("REPO_DIR", "/home/ivan/olt-cdata-zabbix/repo")


def api(m, p):
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    d = json.dumps({"jsonrpc": "2.0", "method": m, "params": p, "id": 1}).encode()
    r = urllib.request.Request(URL, data=d,
        headers={"Content-Type": "application/json-rpc", "Authorization": "Bearer " + TOKEN}, method="POST")
    res = json.loads(urllib.request.urlopen(r, context=ctx, timeout=120).read())
    if "error" in res:
        print("ERR", m, json.dumps(res["error"], ensure_ascii=False)); return None
    return res.get("result")


os.makedirs(OUT + "/zabbix", exist_ok=True)
os.makedirs(OUT + "/dashboards", exist_ok=True)

tpl = api("configuration.export", {"options": {"templates": [TPL]}, "format": "yaml"})
open(OUT + "/zabbix/template_C-Data_FD1304E-B1_EPON_OLT.yaml", "w").write(tpl)
print("template yaml bytes:", len(tpl))

ds = api("dashboard.get", {"output": ["dashboardid"], "search": {"name": "OLT "}}) or []
ids = [d["dashboardid"] for d in ds]
full = api("dashboard.get", {"dashboardids": ids, "selectPages": "extend"}) if ids else []
open(OUT + "/dashboards/dashboards_structure.json", "w").write(json.dumps(full, indent=2, ensure_ascii=False))
print("dashboards dumped:", ids)
