#!/usr/bin/env python3
"""
Create Zabbix template "C-Data FD1304E-B1 EPON OLT" with SNMP LLD for
ONUs (subscriber optical signals) and interfaces, and optionally link it to a host.

Usage:
    export ZABBIX_URL="https://zabbix.example.com/api_jsonrpc.php"
    export ZABBIX_TOKEN="<api token>"
    export ZABBIX_HOSTID="<host id>"        # optional: link the template to this host
    python3 create_cdata_template.py

Verified facts (from live snmpwalk + Zabbix 7.4.5 probing):
  * SNMP item OID supports prefixes:  get[<oid>]  and  walk[<oid>]
    walk[] returns raw "<numeric oid> = TYPE: value" lines.
  * Preprocessing type constants: 1=multiplier, 5=regexp, 10=change/s, 12=JSONPath,
    21=JS, 26=validate-not-supported. (21 used below for normalisation.)
  * ONU name table     .1.3.6.1.4.1.17409.2.3.4.1.1.2   index = ONU_ID
  * ONU online (1/2)   .1.3.6.1.4.1.17409.2.3.4.1.1.8   index = ONU_ID
  * ONU uptime         .1.3.6.1.4.1.17409.2.3.4.1.1.18  index = ONU_ID
  * ONU Rx             .1.3.6.1.4.1.17409.2.3.4.2.1.4   index = ONU_ID.1.PORT  (0.01 dBm)
  * ONU Tx             .1.3.6.1.4.1.17409.2.3.4.2.1.5   index = ONU_ID.1.PORT  (0.01 dBm)
  * ONU voltage        .1.3.6.1.4.1.17409.2.3.4.2.1.6   (mV)
  * ONU temperature    .1.3.6.1.4.1.17409.2.3.4.2.1.7   (0.0001 C)
  * ONU bias current   .1.3.6.1.4.1.17409.2.3.4.2.1.8   (uA)
  * ifDescr            .1.3.6.1.2.1.2.2.1.2            index = ifIndex
  * EPON onu counts    .1.3.6.1.4.1.17409.2.3.3.5.1.{4,5,6}.1.1  index = epon ifIndex
"""
import json, ssl, urllib.request, os

URL = os.environ.get("ZABBIX_URL", "https://zabbix.example.com/api_jsonrpc.php")
TOKEN = os.environ.get("ZABBIX_TOKEN", "")
HOST_ID = os.environ.get("ZABBIX_HOSTID", "")   # host to link the template to (optional)
TEST_TPL = os.environ.get("ZABBIX_TEST_TEMPLATEID", "")  # optional test template to clean up
TPL_ID = None              # set in main()

TPL_HOST = "C-Data_FD1304E-B1_EPON_OLT"
TPL_NAME = "C-Data FD1304E-B1 EPON OLT"
GROUP_NAME = "CDATA"
TPL_DESC = """C-Data FD1304E-B1 - EPON OLT monitoring via SNMP (BDCOM/C-Data enterprise OID .1.3.6.1.4.1.17409).

LLD (low-level discovery) over SNMP walk:
  * ONU discovery  - subscriber name/state (online/offline), optical parameters:
                     Rx/Tx power (dBm), voltage (V), temperature (C), bias current (mA), uptime
  * Interface LLD  - admin/oper status, speed, in/out octets, in/out traffic (bps), in/out errors

Implementation notes:
  * Master items use SNMP OID "walk[<oid>]" + JavaScript preprocessing that converts
    the raw walk text into a JSON array [{idx,val}] used by dependent LLD/item prototypes.
  * Zabbix 7.4.5 substitutes the LLD macro {#SNMPINDEX} inside preprocessing parameters
    as '#<value>' (stray '#'), so per-ONU/port extraction is done in JavaScript
    (see the "JavaScript" preprocessing step of the item prototypes).

Requires host macros: {$SNMP_COMMUNITY}.
Tuning macros: {$CDATA.ONU.RX_MIN} (-26), {$CDATA.ONU.RX_OK} (-24), {$CDATA.ONU.TEMP_MAX} (60),
               {$CDATA.IF.ERRORS_WARN} (1).

Tags (use them to look at one subscriber/interface only):
  * ONU items/triggers:      scope=onu, component=olt, subscriber=<ONU name>, onu_id=<ONU id>
  * Interface items/triggers: scope=port, component=olt, interface=<ifName>, ifindex=<ifIndex>
  In Monitoring -> Latest data / Problems click a tag value to filter by this subscriber.

Graph prototypes (for the built-in "Graph prototype" dashboard widget):
  * ONU [{#SNMPVALUE}] optical signal  - Rx/Tx (dBm)
  * Interface [{#SNMPVALUE}] traffic   - in/out bps
  * Interface [{#SNMPVALUE}] errors    - in/out error packets

Dashboards are created by create_dashboards.py:
  * "OLT olt_len204 - Абонент (метрики одного абонента)"
  * "OLT olt_len204 - Абонентские интерфейсы (EPON)"

Note: the "[<if>] port is down" trigger fires for every interface with ifAdminStatus=up and
ifOperStatus=down, including spare (unconnected) ports. Disable it if it is too noisy.
"""
C = TPL_HOST  # template technical name used inside trigger expressions


def api(method, params):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    data = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(
        URL, data=data,
        headers={"Content-Type": "application/json-rpc", "Authorization": f"Bearer {TOKEN}"},
        method="POST")
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        res = json.loads(r.read())
    if "error" in res:
        raise RuntimeError(f"{method}: {json.dumps(res['error'], ensure_ascii=False)}")
    return res.get("result")


def pp(t, params, eh="0", ehp=""):
    return {"type": str(t), "params": params, "error_handler": str(eh), "error_handler_params": ehp}


def js_normalize(base_oid, magic=False):
    """JS preprocessing turning 'walk[]' text output into a JSON array."""
    idx_assign = "var idx = oid.substring(base.length + 1);\n    var d = idx.indexOf('.');\n    if (d > 0) { idx = idx.substring(0, d); }"
    head = 'var base = "%s";\n' % base_oid
    tail = ('    var v = (c < 0) ? rest : rest.substring(c + 2);\n'
            '    if (v.length > 1 && v.charAt(0) === \'"\' && v.charAt(v.length - 1) === \'"\') '
            '{ v = v.substring(1, v.length - 1); }\n')
    loop = ('var lines = value.split("\\n");\n'
            'var out = [];\n'
            'for (var i = 0; i < lines.length; i++) {\n'
            '    var line = lines[i];\n'
            '    var eq = line.indexOf(" = ");\n'
            '    if (eq < 1) { continue; }\n'
            '    var oid = line.substring(0, eq);\n'
            '    var rest = line.substring(eq + 3);\n'
            '    var c = rest.indexOf(": ");\n')
    if magic:
        keys = ('var ki = "{" + "#SNMPINDEX}";\n'
                'var kv = "{" + "#SNMPVALUE}";\n')
        push = '    var o = {}; o[ki] = idx; o[kv] = v; out.push(o);\n'
    else:
        keys = ''
        push = '    out.push({idx: idx, val: v});\n'
    return (head + keys + loop + tail + '    ' + idx_assign + '\n' + push +
            '}\nreturn JSON.stringify(out);')

def js_extract():
    """JS preprocessing: pick this entity's value out of the master walk JSON.

    NOTE: Zabbix 7.4.5 substitutes the LLD macro {#SNMPINDEX} inside
    preprocessing parameters as "#<value>" (a stray '#' is kept from the
    macro name), therefore the leading '#' is stripped defensively.
    """
    return ('var id = "{#SNMPINDEX}".replace(/^#/, "");\n'
            'var data = JSON.parse(value);\n'
            'for (var i = 0; i < data.length; i++) {\n'
            '    if (data[i].idx === id) { return data[i].val; }\n'
            '}\n'
            'return "";')


def get_or_create_template():
    tid = api("template.get", {"output": ["templateid"], "filter": {"host": TPL_HOST}})
    if tid:
        return tid[0]["templateid"], False
    gid = api("templategroup.get", {"output": ["groupid"], "filter": {"name": GROUP_NAME}})
    gid = gid[0]["groupid"] if gid else \
        api("templategroup.create", {"name": GROUP_NAME})["groupids"][0]
    r = api("template.create", {"host": TPL_HOST, "name": TPL_NAME,
                                "groups": [{"groupid": gid}]})
    return r["templateids"][0], True


def item_get_or_create(tid, spec):
    found = api("item.get", {"output": ["itemid"], "templateids": tid,
                             "filter": {"key_": spec["key_"]}})
    if found:
        return found[0]["itemid"], False
    spec = dict(spec, hostid=tid)
    return api("item.create", spec)["itemids"][0], True


def rule_get_or_create(tid, spec):
    found = api("discoveryrule.get", {"output": ["itemid"], "templateids": tid,
                                      "filter": {"key_": spec["key_"]}})
    if found:
        return found[0]["itemid"], False
    spec = dict(spec, hostid=tid)
    return api("discoveryrule.create", spec)["itemids"][0], True


def proto_get_or_create(lldid, spec):
    found = api("itemprototype.get", {"output": ["itemid"], "discoveryids": lldid,
                                      "filter": {"key_": spec["key_"]}})
    if found:
        if spec.get("tags"):
            api("itemprototype.update", {"itemid": found[0]["itemid"], "tags": spec["tags"]})
        return found[0]["itemid"], False
    spec = dict(spec, ruleid=lldid, hostid=TPL_ID)
    return api("itemprototype.create", spec)["itemids"][0], True


def trigproto_get_or_create(lldid, spec):
    found = api("triggerprototype.get", {"output": ["triggerid"], "discoveryids": lldid,
                                         "filter": {"description": spec["description"]}})
    if found:
        if spec.get("tags"):
            api("triggerprototype.update", {"triggerid": found[0]["triggerid"], "tags": spec["tags"]})
        return found[0]["triggerid"], False
    spec = dict(spec)
    return api("triggerprototype.create", spec)["triggerids"][0], True


def graphproto_get_or_create(lldid, name, gitems, width=900, height=200):
    found = api("graphprototype.get", {"output": ["graphid"], "discoveryids": lldid,
                                       "filter": {"name": name}})
    if found:
        return found[0]["graphid"], False
    r = api("graphprototype.create", {"name": name, "width": width, "height": height,
                                      "show_legend": 1, "gitems": gitems, "hostid": TPL_ID})
    return r["graphids"][0], True


def valuemap_get_or_create(name, mappings, hostid):
    found = api("valuemap.get", {"output": ["valuemapid"], "hostids": hostid,
                                 "filter": {"name": name}})
    if found:
        return found[0]["valuemapid"]
    maps = [{"value": str(v), "newvalue": n, "type": "0"} for v, n in mappings]
    return api("valuemap.create", {"name": name, "hostid": hostid,
                                   "mappings": maps})["valuemapids"][0]


def main():
    global TPL_ID
    tid, created = get_or_create_template()
    TPL_ID = tid
    print(f"Template {'created' if created else 'exists'}: {TPL_HOST} (id={tid})")
    api("template.update", {"templateid": tid, "description": TPL_DESC})

    vm_onu = valuemap_get_or_create("C-Data ONU state", [("1", "Online"), ("2", "Offline")], tid)
    vm_if = valuemap_get_or_create("C-Data interface state", [("1", "up"), ("2", "down")], tid)
    print(f"Value maps: onu={vm_onu} if={vm_if}")

    print("\n=== Template macros ===")
    for m in ({"macro": "{$CDATA.ONU.RX_MIN}", "value": "-26", "description": "Warning: ONU Rx power below this (dBm)"},
              {"macro": "{$CDATA.ONU.RX_OK}", "value": "-24", "description": "Recovery threshold for ONU Rx power (dBm)"},
              {"macro": "{$CDATA.ONU.TEMP_MAX}", "value": "60", "description": "Max ONU temperature (C)"},
              {"macro": "{$CDATA.IF.ERRORS_WARN}", "value": "1", "description": "Interface error delta threshold"}):
        if not api("usermacro.get", {"hostids": tid, "filter": {"macro": m["macro"]}}):
            api("usermacro.create", dict(m, hostid=tid))
            print("  +", m["macro"], "=", m["value"])

    # ---------------- system items ----------------
    print("\n=== System items ===")
    sysitems = [
        ("Device name", "cdata.system.name", ".1.3.6.1.2.1.1.5.0", 4, "5m", None, None),
        ("Device description", "cdata.system.descr", ".1.3.6.1.2.1.1.1.0", 4, "1h", None, None),
        ("Device object ID", "cdata.system.objectid", ".1.3.6.1.2.1.1.2.0", 1, "1h", None, None),
        ("Device uptime", "cdata.system.uptime", ".1.3.6.1.2.1.1.3.0", 3, "5m", "uptime", None),
        ("Device location", "cdata.system.location", ".1.3.6.1.2.1.1.6.0", 1, "1h", None, None),
        ("Device contact", "cdata.system.contact", ".1.3.6.1.2.1.1.4.0", 1, "1h", None, None),
    ]
    for name, key, oid, vt, delay, units, vmap in sysitems:
        s = {"name": name, "key_": key, "type": 20, "delay": delay, "snmp_oid": oid,
             "value_type": vt, "description": f"SNMP OID {oid}"}
        if units:
            s["units"] = units
        if vmap:
            s["valuemapid"] = vmap
        _, isnew = item_get_or_create(tid, s)
        print(f"  {'+' if isnew else '='} {key}")


    # ---------------- SNMP walk master items ----------------
    print("\n=== SNMP walk master items ===")
    ONU_BASE = ".1.3.6.1.4.1.17409.2.3.4"
    IF_BASE = ".1.3.6.1.2.1.2.2.1"
    EPON_BASE = ".1.3.6.1.4.1.17409.2.3.3.5.1"

    # key, name, walk base oid, json mode ('magic'|'plain'), delay
    walks = [
        ("cdata.onu.name", "ONU names (walk)", f"{ONU_BASE}.1.1.2", "magic", "1m"),
        ("cdata.onu.state", "ONU online state (walk)", f"{ONU_BASE}.1.1.8", "plain", "1m"),
        ("cdata.onu.uptime", "ONU uptime (walk)", f"{ONU_BASE}.1.1.18", "plain", "5m"),
        ("cdata.onu.rx", "ONU Rx power (walk)", f"{ONU_BASE}.2.1.4", "plain", "1m"),
        ("cdata.onu.tx", "ONU Tx power (walk)", f"{ONU_BASE}.2.1.5", "plain", "1m"),
        ("cdata.onu.voltage", "ONU voltage (walk)", f"{ONU_BASE}.2.1.6", "plain", "2m"),
        ("cdata.onu.temp", "ONU temperature (walk)", f"{ONU_BASE}.2.1.7", "plain", "2m"),
        ("cdata.onu.bias", "ONU bias current (walk)", f"{ONU_BASE}.2.1.8", "plain", "5m"),
        ("cdata.if.name", "Interface names (walk)", f"{IF_BASE}.2", "magic", "2m"),
        ("cdata.if.admin", "Interface admin status (walk)", f"{IF_BASE}.7", "plain", "2m"),
        ("cdata.if.oper", "Interface oper status (walk)", f"{IF_BASE}.8", "plain", "2m"),
        ("cdata.if.speed", "Interface speed (walk)", f"{IF_BASE}.5", "plain", "5m"),
        ("cdata.if.inerrors", "Interface input errors (walk)", f"{IF_BASE}.14", "plain", "2m"),
        ("cdata.if.outerrors", "Interface output errors (walk)", f"{IF_BASE}.20", "plain", "2m"),
        ("cdata.if.inoctets", "Interface input octets (walk)", f"{IF_BASE}.10", "plain", "2m"),
        ("cdata.if.outoctets", "Interface output octets (walk)", f"{IF_BASE}.16", "plain", "2m"),
    ]
    for key, name, oid, mode, delay in walks:
        s = {"name": name, "key_": key, "type": 20, "delay": delay,
             "snmp_oid": f"walk[{oid}]", "value_type": 4,
             "description": f"SNMP walk {oid}; JSON normalised for LLD recursion.",
             "preprocessing": [pp(21, js_normalize(oid, magic=(mode == "magic")))]}
        _, isnew = item_get_or_create(tid, s)
        print(f"  {'+' if isnew else '='} {key}  walk[{oid}]")

    # ---------------- LLD: ONUs ----------------
    print("\n=== LLD rule: ONU ===")
    onu_master = api("item.get", {"output": ["itemid"], "templateids": tid,
                                  "filter": {"key_": "cdata.onu.name"}})[0]["itemid"]
    onu_lld, _ = rule_get_or_create(tid, {
        "name": "ONU discovery", "key_": "cdata.onu.lld", "type": 18,
        "master_itemid": onu_master, "delay": "0", "lifetime": "7d",
        "description": "Discovers EPON ONUs by SNMP walk of the ONU name table.",
    })
    print("  lld id:", onu_lld)

    INT_RE = r"^-?[0-9]+$"
    NUM_RE = r"^-?[0-9]+(\.[0-9]+)?$"
    ONU_TAGS = [{"tag": "scope", "value": "onu"}, {"tag": "component", "value": "olt"},
                {"tag": "subscriber", "value": "{#SNMPVALUE}"}, {"tag": "onu_id", "value": "{#SNMPINDEX}"}]
    IF_TAGS = [{"tag": "scope", "value": "port"}, {"tag": "component", "value": "olt"},
               {"tag": "interface", "value": "{#SNMPVALUE}"}, {"tag": "ifindex", "value": "{#SNMPINDEX}"}]

    def onu_proto(label, key, master_key, units, vt, num_re=INT_RE, preproc_extra=None, valuemapid=None):
        master = api("item.get", {"output": ["itemid"], "templateids": tid,
                                  "filter": {"key_": master_key}})[0]["itemid"]
        pre = [pp(21, js_extract()), pp(14, num_re, eh="1")]
        if preproc_extra:
            pre += preproc_extra
        s = {"name": f"ONU [{{#SNMPVALUE}}] {label}", "key_": key, "type": 18, "delay": "0",
             "master_itemid": master, "value_type": vt, "units": units, "preprocessing": pre,
             "tags": ONU_TAGS}
        if valuemapid:
            s["valuemapid"] = valuemapid
        _, isnew = proto_get_or_create(onu_lld, s)
        print(f"  {'+' if isnew else '='} {key}")

    onu_proto("State", "cdata.onu.state[{#SNMPINDEX}]", "cdata.onu.state", "", 3, valuemapid=vm_onu)
    onu_proto("Rx power", "cdata.onu.rx[{#SNMPINDEX}]", "cdata.onu.rx", "dBm", 0, NUM_RE, [pp(1, "0.01")])
    onu_proto("Tx power", "cdata.onu.tx[{#SNMPINDEX}]", "cdata.onu.tx", "dBm", 0, NUM_RE, [pp(1, "0.01")])
    onu_proto("Voltage", "cdata.onu.voltage[{#SNMPINDEX}]", "cdata.onu.voltage", "V", 0, NUM_RE, [pp(1, "0.001")])
    onu_proto("Temperature", "cdata.onu.temp[{#SNMPINDEX}]", "cdata.onu.temp", "C", 0, NUM_RE, [pp(1, "0.0001")])
    onu_proto("Bias current", "cdata.onu.bias[{#SNMPINDEX}]", "cdata.onu.bias", "mA", 0, NUM_RE, [pp(1, "0.001")])
    onu_proto("Uptime", "cdata.onu.uptime[{#SNMPINDEX}]", "cdata.onu.uptime", "uptime", 3)


    # ---------------- LLD: interfaces ----------------
    print("\n=== LLD rule: interfaces ===")
    if_master = api("item.get", {"output": ["itemid"], "templateids": tid,
                                 "filter": {"key_": "cdata.if.name"}})[0]["itemid"]
    if_lld, _ = rule_get_or_create(tid, {
        "name": "Interface discovery", "key_": "cdata.if.lld", "type": 18,
        "master_itemid": if_master, "delay": "0", "lifetime": "7d",
        "description": "Discovers physical/EPON interfaces by SNMP walk of ifDescr.",
    })
    print("  lld id:", if_lld)

    def if_proto(label, key, master_key, units, vt, num_re=INT_RE, preproc_extra=None, valuemapid=None):
        master = api("item.get", {"output": ["itemid"], "templateids": tid,
                                  "filter": {"key_": master_key}})[0]["itemid"]
        pre = [pp(21, js_extract()), pp(14, num_re, eh="1")]
        if preproc_extra:
            pre += preproc_extra
        s = {"name": f"Interface [{{#SNMPVALUE}}] {label}", "key_": key, "type": 18, "delay": "0",
             "master_itemid": master, "value_type": vt, "units": units, "preprocessing": pre,
             "tags": IF_TAGS}
        if valuemapid:
            s["valuemapid"] = valuemapid
        _, isnew = proto_get_or_create(if_lld, s)
        print(f"  {'+' if isnew else '='} {key}")

    if_proto("Admin status", "cdata.if.admin[{#SNMPINDEX}]", "cdata.if.admin", "", 3, valuemapid=vm_if)
    if_proto("Oper status", "cdata.if.oper[{#SNMPINDEX}]", "cdata.if.oper", "", 3, valuemapid=vm_if)
    if_proto("Speed", "cdata.if.speed[{#SNMPINDEX}]", "cdata.if.speed", "bps", 3)
    if_proto("In errors", "cdata.if.inerrors[{#SNMPINDEX}]", "cdata.if.inerrors", "", 3)
    if_proto("Out errors", "cdata.if.outerrors[{#SNMPINDEX}]", "cdata.if.outerrors", "", 3)
    if_proto("In octets", "cdata.if.inoctets[{#SNMPINDEX}]", "cdata.if.inoctets", "B", 3)
    if_proto("Out octets", "cdata.if.outoctets[{#SNMPINDEX}]", "cdata.if.outoctets", "B", 3)
    if_proto("In traffic", "cdata.if.inbps[{#SNMPINDEX}]", "cdata.if.inoctets", "bps", 0, INT_RE,
             [pp(10, ""), pp(1, "8")])
    if_proto("Out traffic", "cdata.if.outbps[{#SNMPINDEX}]", "cdata.if.outoctets", "bps", 0, INT_RE,
             [pp(10, ""), pp(1, "8")])


    # ---------------- trigger prototypes ----------------
    print("\n=== Trigger prototypes ===")

    def tproto(desc, expr, priority, recovery=None, scope="onu"):
        s = {"description": desc, "expression": expr, "priority": priority,
             "tags": ONU_TAGS if scope == "onu" else IF_TAGS}
        if recovery:
            s["recovery_mode"] = 1
            s["recovery_expression"] = recovery
        _, isnew = trigproto_get_or_create(onu_lld if scope == "onu" else if_lld, s)
        print(f"  {'+' if isnew else '='} {desc}")

    tproto("ONU [{#SNMPVALUE}] Rx power below {$CDATA.ONU.RX_MIN} dBm",
           f"last(/{C}/cdata.onu.rx[{{#SNMPINDEX}}]) < {{$CDATA.ONU.RX_MIN}}", 4,
           f"last(/{C}/cdata.onu.rx[{{#SNMPINDEX}}]) > {{$CDATA.ONU.RX_OK}}")
    tproto("ONU [{#SNMPVALUE}] offline",
           f"last(/{C}/cdata.onu.state[{{#SNMPINDEX}}]) = 2", 3,
           f"last(/{C}/cdata.onu.state[{{#SNMPINDEX}}]) = 1")
    tproto("ONU [{#SNMPVALUE}] optical data missing (offline/no signal)",
           f"nodata(/{C}/cdata.onu.rx[{{#SNMPINDEX}}],20m) = 1", 2)
    tproto("ONU [{#SNMPVALUE}] temperature above {$CDATA.ONU.TEMP_MAX} C",
           f"last(/{C}/cdata.onu.temp[{{#SNMPINDEX}}]) > {{$CDATA.ONU.TEMP_MAX}}", 2,
           f"last(/{C}/cdata.onu.temp[{{#SNMPINDEX}}]) < {{$CDATA.ONU.TEMP_MAX}} - 5")
    tproto("ONU [{#SNMPVALUE}] Tx power out of range",
           f"last(/{C}/cdata.onu.tx[{{#SNMPINDEX}}]) < 0 or last(/{C}/cdata.onu.tx[{{#SNMPINDEX}}]) > 5", 2,
           f"last(/{C}/cdata.onu.tx[{{#SNMPINDEX}}]) >= 0 and last(/{C}/cdata.onu.tx[{{#SNMPINDEX}}]) <= 5")

    tproto("[{#SNMPVALUE}] port is down",
           f"last(/{C}/cdata.if.admin[{{#SNMPINDEX}}]) = 1 and last(/{C}/cdata.if.oper[{{#SNMPINDEX}}]) = 2", 3,
           f"last(/{C}/cdata.if.oper[{{#SNMPINDEX}}]) = 1", scope="port")
    tproto("[{#SNMPVALUE}] input errors detected",
           f"change(/{C}/cdata.if.inerrors[{{#SNMPINDEX}}]) > {{$CDATA.IF.ERRORS_WARN}}", 2,
           f"change(/{C}/cdata.if.inerrors[{{#SNMPINDEX}}]) = 0", scope="port")
    tproto("[{#SNMPVALUE}] output errors detected",
           f"change(/{C}/cdata.if.outerrors[{{#SNMPINDEX}}]) > {{$CDATA.IF.ERRORS_WARN}}", 2,
           f"change(/{C}/cdata.if.outerrors[{{#SNMPINDEX}}]) = 0", scope="port")

    # ---------------- graph prototypes (for "Graph prototype" dashboard widget) ----------------
    print("\n=== Graph prototypes ===")

    def pid(lld, key):
        r = api("itemprototype.get", {"output": ["itemid"], "discoveryids": lld, "filter": {"key_": key}})
        return r[0]["itemid"]

    g, isnew = graphproto_get_or_create(onu_lld, "ONU [{#SNMPVALUE}] optical signal", [
        {"itemid": pid(onu_lld, "cdata.onu.rx[{#SNMPINDEX}]"), "color": "1E90FF", "drawtype": 0, "sortorder": 0},
        {"itemid": pid(onu_lld, "cdata.onu.tx[{#SNMPINDEX}]"), "color": "FF9800", "drawtype": 0, "sortorder": 1}])
    print(f"  {'+' if isnew else '='} ONU optical signal graph: {g}")
    g, isnew = graphproto_get_or_create(if_lld, "Interface [{#SNMPVALUE}] traffic", [
        {"itemid": pid(if_lld, "cdata.if.inbps[{#SNMPINDEX}]"), "color": "4CAF50", "drawtype": 0, "sortorder": 0},
        {"itemid": pid(if_lld, "cdata.if.outbps[{#SNMPINDEX}]"), "color": "1E90FF", "drawtype": 0, "sortorder": 1}])
    print(f"  {'+' if isnew else '='} Interface traffic graph: {g}")
    g, isnew = graphproto_get_or_create(if_lld, "Interface [{#SNMPVALUE}] errors", [
        {"itemid": pid(if_lld, "cdata.if.inerrors[{#SNMPINDEX}]"), "color": "F44336", "drawtype": 0, "sortorder": 0},
        {"itemid": pid(if_lld, "cdata.if.outerrors[{#SNMPINDEX}]"), "color": "FF9800", "drawtype": 0, "sortorder": 1}])
    print(f"  {'+' if isnew else '='} Interface errors graph: {g}")

    # ---------------- cleanup test artifacts ----------------
    if TEST_TPL:
        print(f"\n=== Cleanup test artifacts in template {TEST_TPL} ===")
        prefixes = ("test.", "probe.", "p28.", "p29.", "p30.", "q28.", "q29.", "z.")
        for it in api("item.get", {"templateids": TEST_TPL, "output": ["itemid", "key_"]}) or []:
            if it["key_"].startswith(prefixes):
                api("item.delete", [it["itemid"]])
                print("  - deleted", it["key_"])

    # ---------------- link template to host ----------------
    if HOST_ID:
        print(f"\n=== Link template to host {HOST_ID} ===")
        h = api("host.get", {"hostids": HOST_ID, "selectParentTemplates": ["templateid"]})
        cur = [t["templateid"] for t in h[0].get("parentTemplates", [])
               if not TEST_TPL or t["templateid"] != TEST_TPL]
        if tid not in cur:
            cur.append(tid)
            api("host.update", {"hostid": HOST_ID,
                                "templates": [{"templateid": x} for x in cur]})
            print("  linked:", cur)
        else:
            print("  already linked; templates:", cur)
    else:
        print("\n=== Link template to host: skipped (set ZABBIX_HOSTID to do it automatically) ===")

    print("\n=== DONE ===")
    print(f"Template id: {tid}")


if __name__ == "__main__":
    main()

