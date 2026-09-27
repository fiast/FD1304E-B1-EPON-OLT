#!/usr/bin/env python3
import json, ssl, urllib.request, os, sys
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


HOSTS = sys.argv[1:] or ["olt_len204", "olt_snt1", "olt_ulej7", "olt_lenina2",
                         "olt_fedorenko10", "olt_melio7"]
for hn in HOSTS:
    h = api("host.get", {"output": ["hostid", "status"], "filter": {"host": hn},
                         "selectParentTemplates": ["host"]})
    if not h:
        print(f"\n### {hn}: NOT FOUND"); continue
    hid = h[0]["hostid"]
    print(f"\n### {hn} id={hid} status={h[0]['status']} templates={[t['host'] for t in h[0]['parentTemplates']]}")
    masters = [i for i in api("item.get", {"hostids": hid, "output": ["key_", "state", "error", "lastclock"]})
               if "." in i["key_"] and "[" not in i["key_"] and not i["key_"].startswith("net.")
               and not i["key_"].startswith("icmp") and not i["key_"].startswith("zabbix")]
    ok = [i for i in masters if i["state"] == "0" and i["lastclock"] != "0"]
    bad = [i for i in masters if i["state"] != "0"]
    print(f"   masters: total={len(masters)} collecting={len(ok)} unsupported={len(bad)}")
    for i in bad[:6]:
        print(f"     ! {i['key_']:<24} state={i['state']} err={i['error'][:60]!r}")
    for pat, label in (("gas.onu.mac[", "ONU (Gateray)"), ("gas.onu.rx[", "ONU Rx (Gateray)"),
                       ("cdata.onu.rx[", "ONU Rx"), ("if.oper[", "interface oper"),
                       ("if.inbps[", "interface traffic")):
        items = api("item.get", {"hostids": hid, "output": ["key_", "state", "lastvalue", "lastclock"],
                                 "search": {"key_": pat}})
        coll = [i for i in items if i["lastclock"] != "0"]
        sample = "; ".join(f"{i['key_'].split('[')[1][:-1]}={i['lastvalue']}" for i in coll[:4])
        print(f"   {label:<20} found={len(items):<4} with data={len(coll):<4} {sample[:70]}")
