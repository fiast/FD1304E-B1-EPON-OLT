#!/usr/bin/env python3
"""Delete leftover probe items (keys starting with 't.') from all hosts."""
import json, ssl, urllib.request, os

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


for i in api("item.get", {"output": ["itemid", "key_", "hostid"], "searchWildcardsEnabled": True,
                          "search": {"key_": "t.*"}}):
    if i["key_"].split(".")[0] == "t":
        api("item.delete", [i["itemid"]])
        print("deleted", i["key_"], "host", i["hostid"])
print("done")
