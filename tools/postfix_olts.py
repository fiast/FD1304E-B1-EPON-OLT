#!/usr/bin/env python3
"""Post-deployment fixes: detach wrong template from olt_len204, soften SNMP for weak OLTs."""
import json, ssl, urllib.request, os

URL = os.environ["ZABBIX_URL"]; TOKEN = os.environ["ZABBIX_TOKEN"]
KEEP = "C-Data_FD1304E-B1_EPON_OLT"
SOFTEN = {"olt_snt1": "10678", "olt_ulej7": "10677"}   # hosts that report 'partial data'


def api(m, p):
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    d = json.dumps({"jsonrpc": "2.0", "method": m, "params": p, "id": 1}).encode()
    r = urllib.request.Request(URL, data=d,
        headers={"Content-Type": "application/json-rpc", "Authorization": "Bearer " + TOKEN}, method="POST")
    res = json.loads(urllib.request.urlopen(r, context=ctx, timeout=60).read())
    if "error" in res:
        print("ERR", m, res["error"]); return []
    return res.get("result") or []


# 1) olt_len204 keeps only the C-Data template
h = api("host.get", {"hostids": "10706", "selectParentTemplates": ["templateid", "host"]})[0]
keep_id = api("template.get", {"output": ["templateid"], "filter": {"host": KEEP}})[0]["templateid"]
cur = [t["templateid"] for t in h["parentTemplates"]]
if cur != [keep_id]:
    api("host.update", {"hostid": "10706", "templates": [{"templateid": keep_id}]})
    print("len204: templates set to", [KEEP])
else:
    print("len204: ok")

# 2) SNMP: disable bulk requests on weak OLTs (fixes 'only partial data received')
for name, hid in SOFTEN.items():
    for i in api("hostinterface.get", {"hostids": hid, "output": ["interfaceid", "details"]}):
        det = dict(i["details"])
        det["bulk"] = "0"
        det["max_repetitions"] = "1"
        api("hostinterface.update", {"interfaceid": i["interfaceid"], "details": det})
        print(f"{name}: bulk=0, max_repetitions=1")
