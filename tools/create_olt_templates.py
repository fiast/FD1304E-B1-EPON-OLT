#!/usr/bin/env python3
"""Create Zabbix templates for BDCOM P3310B and Gateray GR-EP-OLT EPON OLTs.

Same techniques as in create_cdata_template.py: SNMP items with OID "walk[<oid>]" +
JavaScript preprocessing -> JSON [{idx,val}], dependent LLD rules, dependent item
prototypes (per-item extraction in JavaScript), tags, triggers.

NOTE (Zabbix 7.4.5): the LLD macro {#SNMPINDEX} inside preprocessing parameters is
substituted as "#<value>", so extraction strips the leading '#' in JavaScript.

Env: ZABBIX_URL, ZABBIX_TOKEN, ZABBIX_HOSTID (optional: link templates to this host)
"""
import json, os, ssl, urllib.request

URL = os.environ.get("ZABBIX_URL", "https://zabbix.example.com/api_jsonrpc.php")
TOKEN = os.environ.get("ZABBIX_TOKEN", "")
HOST_ID = os.environ.get("ZABBIX_HOSTID", "")
TPL_ID = None


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


def pp(t, params, eh="0", ehp=""):
    return {"type": str(t), "params": params, "error_handler": str(eh), "error_handler_params": ehp}


JS_HEAD = ('var base = "%s";\n'
           'var lines = value.split("\\n");\n'
           'var out = [];\n'
           'for (var i = 0; i < lines.length; i++) {\n'
           '    var line = lines[i];\n'
           '    var eq = line.indexOf(" = ");\n'
           '    if (eq < 1) { continue; }\n'
           '    var oid = line.substring(0, eq);\n'
           '    var rest = line.substring(eq + 3);\n'
           '    var c = rest.indexOf(": ");\n'
           '    var v = (c < 0) ? rest : rest.substring(c + 2);\n'
           '    if (v.length > 1 && v.charAt(0) === \'"\' && v.charAt(v.length - 1) === \'"\') '
           '{ v = v.substring(1, v.length - 1); }\n'
           '    var idx = oid.substring(base.length + 1);\n'
           '    var d = idx.indexOf(".");\n'
           '    if (d > 0) { idx = idx.substring(0, d); }\n')

JS_EXTRACT = ('var id = "{#SNMPINDEX}".replace(/^#/, "");\n'
              'var data = JSON.parse(value);\n'
              'for (var i = 0; i < data.length; i++) {\n'
              '    if (data[i].idx === id) { return data[i].val; }\n'
              '}\n'
              'return "";')

INT_RE = r"^-?[0-9]+$"
NUM_RE = r"^-?[0-9]+(\.[0-9]+)?$"


def js_plain(base_oid):
    return (JS_HEAD % base_oid) + '    out.push({idx: idx, val: v});\n}\nreturn JSON.stringify(out);'


def js_magic(base_oid):
    return ((JS_HEAD % base_oid) +
            '    var o = {}; o["{" + "#SNMPINDEX}"] = idx; o["{" + "#SNMPVALUE}"] = v;\n'
            '    out.push(o);\n}\nreturn JSON.stringify(out);')


def js_magic_type(base_oid):
    """magic JSON + extra macro {#IF_TYPE} (GigaEthernet / EPON / GE / PON) parsed from the name."""
    return ((JS_HEAD % base_oid) +
            '    var o = {}; o["{" + "#SNMPINDEX}"] = idx; o["{" + "#SNMPVALUE}"] = v;\n'
            '    var t = v.replace(/^.*[\\s,]/, "").replace(/[0-9].*$/, "").replace(/[-:]+$/, "");\n'
            '    o["{" + "#IF_TYPE}"] = t ? t : v;\n'
            '    out.push(o);\n}\nreturn JSON.stringify(out);')


def js_hex_name(base_oid):
    """Hex-STRING table -> decoded ASCII names (trailing NULs stripped)."""
    return ('var base = "%s";\n'
            'var lines = value.split("\\n");\n'
            'var out = [];\n'
            'for (var i = 0; i < lines.length; i++) {\n'
            '    var line = lines[i];\n'
            '    var eq = line.indexOf(" = ");\n'
            '    if (eq < 1) { continue; }\n'
            '    var oid = line.substring(0, eq);\n'
            '    var rest = line.substring(eq + 3);\n'
            '    var c = rest.indexOf(": ");\n'
            '    var hex = (c < 0) ? rest : rest.substring(c + 2);\n'
            '    hex = hex.replace(/[^0-9A-Fa-f]/g, "");\n'
            '    var s = "";\n'
            '    for (var j = 0; j + 1 < hex.length; j += 2) {\n'
            '        var code = parseInt(hex.substr(j, 2), 16);\n'
            '        if (code === 0) { break; }\n'
            '        s += String.fromCharCode(code);\n'
            '    }\n'
            '    if (s === "") { s = "<unnamed>"; }\n'
            '    var idx = oid.substring(base.length + 1);\n'
            '    var d = idx.indexOf(".");\n'
            '    if (d > 0) { idx = idx.substring(0, d); }\n'
            '    var o = {}; o["{" + "#SNMPINDEX}"] = idx; o["{" + "#SNMPVALUE}"] = s;\n'
            '    out.push(o);\n'
            '}\nreturn JSON.stringify(out);' % base_oid)



def gr_js(base_oid, mode="plain"):
    """JS: parse `snmpwalk` output of a Gateray ONU table into JSON.

    Gateray tables are indexed <PON>.<ONU> (e.g. .7.1.2.5 = column 7, PON 2, ONU 5),
    so the walk base must NOT contain the PON component and the LLD index is "pon_onu".

    mode:
      plain -> [{"idx": "2_5", "val": "<raw>"}]
      magic -> LLD macros {#SNMPINDEX}/{#SNMPVALUE}/{#PON}/{#ONU}
      str   -> like plain, but for quoted STRING values ("" -> "<unnamed>")
    """
    head = ('var base = "%s";\n'
            'var lines = value.split("\\n");\n'
            'var out = [];\n'
            'for (var i = 0; i < lines.length; i++) {\n'
            '    var line = lines[i];\n'
            '    var eq = line.indexOf(" = ");\n'
            '    if (eq < 1) { continue; }\n'
            '    var oid = line.substring(0, eq);\n'
            '    var rest = line.substring(eq + 3);\n'
            '    var c = rest.indexOf(": ");\n'
            '    var v = (c < 0) ? rest : rest.substring(c + 2);\n'
            '    var isHex = (rest.indexOf("Hex-STRING") === 0);\n'
            '    if (v.length > 1 && v.charAt(0) === \'"\' && v.charAt(v.length - 1) === \'"\') '
            '{ v = v.substring(1, v.length - 1); }\n'
            '    var p = oid.substring(base.length + 1).split(".");\n'
            '    if (p.length < 2) { continue; }\n'
            '    var pon = p[p.length - 2];\n'
            '    var onu = p[p.length - 1];\n'
            '    var idx = pon + "_" + onu;\n') % base_oid
    if mode == "magic":
        return (head +
                '    if (v.indexOf(" ") >= 0) {\n'
                '        var mac = v.replace(/[^0-9A-Fa-f]/g, "");\n'
                '        if (mac.length === 12) {\n'
                '            v = "";\n'
                '            for (var j = 0; j < 12; j += 2) { v += (j ? ":" : "") + mac.substr(j, 2).toUpperCase(); }\n'
                '        }\n'
                '    }\n'
                '    var o = {}; o["{" + "#SNMPINDEX}"] = idx; o["{" + "#SNMPVALUE}"] = v;\n'
                '    o["{" + "#PON}"] = pon; o["{" + "#ONU}"] = onu;\n'
                '    out.push(o);\n'
                '}\nreturn JSON.stringify(out);')
    if mode == "str":
        return (head +
                '    if (isHex) {\n'
                '        var h = v.replace(/[^0-9A-Fa-f]/g, "");\n'
                '        var s = "";\n'
                '        for (var j = 0; j + 1 < h.length; j += 2) {\n'
                '            var code = parseInt(h.substr(j, 2), 16);\n'
                '            if (code === 0) { break; }\n'
                '            s += String.fromCharCode(code);\n'
                '        }\n'
                '        v = s;\n'
                '    }\n'
                '    if (v === "") { v = "<unnamed>"; }\n'
                '    out.push({idx: idx, val: v});\n'
                '}\nreturn JSON.stringify(out);')
    return head + '    out.push({idx: idx, val: v});\n}\nreturn JSON.stringify(out);'


def gr_js_value(kind):
    """JS: raw Gateray value -> physical value.

    Verified against `show olt N optical-online-onu` / the NMS ONU table:
      Rx / Tx power : raw is in 0.1 uW   -> dBm = 10*log10(raw/10000)
      voltage       : raw/10000 V,  bias: raw/500 mA,  temperature: raw/256 C
    Raw 0 (and other sentinels) -> empty string (value is discarded).
    """
    if kind == "dbm":
        return ('var v = parseFloat(value);\n'
                'if (!isFinite(v) || v <= 0 || v > 60000) { return ""; }\n'
                'return 10 * Math.log(v / 10000) / Math.LN10;')
    div = {"volt": "10000", "bias": "500"}.get(kind, "256")
    return ('var v = parseFloat(value);\n'
            'if (!isFinite(v) || v <= 0) { return ""; }\n'
            'return v / ' + div + ';')


def tpl_get_or_create(host, name, group):
    r = api("template.get", {"output": ["templateid"], "filter": {"host": host}})
    if r:
        return r[0]["templateid"], False
    gid = api("templategroup.get", {"output": ["groupid"], "filter": {"name": group}})
    gid = gid[0]["groupid"] if gid else api("templategroup.create", {"name": group})["groupids"][0]
    r = api("template.create", {"host": host, "name": name, "groups": [{"groupid": gid}]})
    return r["templateids"][0], True


def item_upsert(tid, spec, update_preproc=False, update_oid=False):
    f = api("item.get", {"output": ["itemid"], "templateids": tid, "filter": {"key_": spec["key_"]}})
    if f:
        upd = {}
        if update_preproc and spec.get("preprocessing"):
            upd["preprocessing"] = spec["preprocessing"]
        if update_oid and spec.get("snmp_oid"):
            upd["snmp_oid"] = spec["snmp_oid"]
        if upd:
            api("item.update", dict(upd, itemid=f[0]["itemid"]))
        return f[0]["itemid"], False
    return api("item.create", dict(spec, hostid=tid))["itemids"][0], True


def lld_upsert(tid, spec):
    f = api("discoveryrule.get", {"output": ["itemid"], "templateids": tid, "filter": {"key_": spec["key_"]}})
    if f:
        return f[0]["itemid"], False
    return api("discoveryrule.create", dict(spec, hostid=tid))["itemids"][0], True


def proto_upsert(lldid, spec):
    f = api("itemprototype.get", {"output": ["itemid"], "discoveryids": lldid,
                                  "filter": {"key_": spec["key_"]}})
    if f:
        upd = {"itemid": f[0]["itemid"]}
        for k in ("name", "tags", "preprocessing", "params", "master_itemid"):
            if spec.get(k):
                upd[k] = spec[k]
        if len(upd) > 1:
            api("itemprototype.update", upd)
        return f[0]["itemid"], False
    return api("itemprototype.create", dict(spec, ruleid=lldid, hostid=TPL_ID))["itemids"][0], True


def trig_upsert(lldid, spec):
    f = api("triggerprototype.get", {"output": ["triggerid"], "discoveryids": lldid,
                                     "filter": {"description": spec["description"]}})
    if f:
        return f[0]["triggerid"], False
    return api("triggerprototype.create", spec)["triggerids"][0], True


def macro_upsert(tid, macro, value, description=""):
    f = api("usermacro.get", {"hostids": tid, "filter": {"macro": macro}})
    if f:
        api("usermacro.update", {"hostmacroid": f[0]["hostmacroid"], "value": value})
    else:
        api("usermacro.create", {"hostid": tid, "macro": macro, "value": value,
                                 "description": description})


def master(tid, key):
    return api("item.get", {"output": ["itemid"], "templateids": tid,
                            "filter": {"key_": key}})[0]["itemid"]


def link_to_host(tid):
    if not HOST_ID:
        return
    h = api("host.get", {"hostids": HOST_ID, "selectParentTemplates": ["templateid"]})
    cur = [t["templateid"] for t in h[0].get("parentTemplates", [])]
    if tid not in cur:
        cur.append(tid)
        api("host.update", {"hostid": HOST_ID, "templates": [{"templateid": x} for x in cur]})
        print(f"  linked template {tid} to host {HOST_ID}")



def system_items(tid, extra):
    common = [
        ("Device name", "system.name", ".1.3.6.1.2.1.1.5.0", 1, "5m", None),
        ("Device description", "system.descr", ".1.3.6.1.2.1.1.1.0", 4, "1h", None),
        ("Device object ID", "system.objectid", ".1.3.6.1.2.1.1.2.0", 1, "1h", None),
        ("Device uptime", "system.uptime", ".1.3.6.1.2.1.1.3.0", 3, "5m", "uptime"),
        ("Device location", "system.location", ".1.3.6.1.2.1.1.6.0", 1, "1h", None),
        ("Device contact", "system.contact", ".1.3.6.1.2.1.1.4.0", 1, "1h", None),
    ]
    for name, key, oid, vt, delay, units in common + extra:
        s = {"name": name, "key_": key, "type": 20, "delay": delay, "snmp_oid": oid,
             "value_type": vt, "tags": [{"tag": "scope", "value": "system"}]}
        if units:
            s["units"] = units
        _, new = item_upsert(tid, s, update_preproc=True)
        print(f"  {'+' if new else '='} {key}")


def interface_masters(tid, prefix="if"):
    """Standard IF-MIB walk masters + interface-name master with {#IF_TYPE}."""
    base = ".1.3.6.1.2.1.2.2.1"
    walks = [
        (f"{prefix}.admin", "Interface admin status (walk)", f"{base}.7", "2m"),
        (f"{prefix}.oper", "Interface oper status (walk)", f"{base}.8", "2m"),
        (f"{prefix}.speed", "Interface speed (walk)", f"{base}.5", "5m"),
        (f"{prefix}.inerrors", "Interface input errors (walk)", f"{base}.14", "2m"),
        (f"{prefix}.outerrors", "Interface output errors (walk)", f"{base}.20", "2m"),
        (f"{prefix}.inoctets", "Interface input octets (walk)", f"{base}.10", "2m"),
        (f"{prefix}.outoctets", "Interface output octets (walk)", f"{base}.16", "2m"),
    ]
    for key, name, oid, delay in walks:
        s = {"name": name, "key_": key, "type": 20, "delay": delay, "snmp_oid": f"walk[{oid}]",
             "value_type": 4, "preprocessing": [pp(21, js_plain(oid))],
             "description": f"SNMP walk {oid}; JSON normalised for LLD recursion.",
             "tags": [{"tag": "scope", "value": "iface"}]}
        _, new = item_upsert(tid, s, update_preproc=True)
        print(f"  {'+' if new else '='} {key}")
    oid = f"{base}.2"
    s = {"name": "Interface names (walk)", "key_": f"{prefix}.name", "type": 20, "delay": "2m",
         "snmp_oid": f"walk[{oid}]", "value_type": 4,
         "preprocessing": [pp(21, js_magic_type(oid))],
         "description": f"SNMP walk {oid}; JSON normalised for LLD (adds {{#IF_TYPE}}).",
         "tags": [{"tag": "scope", "value": "iface"}]}
    _, new = item_upsert(tid, s, update_preproc=True)
    print(f"  {'+' if new else '='} {prefix}.name")


def iface_lld(tid, tpl_host, if_tags):
    lld, _ = lld_upsert(tid, {"name": "Interface discovery", "key_": "if.lld", "type": 18,
                              "master_itemid": master(tid, "if.name"), "delay": "0", "lifetime": "7d",
                              "description": "Interfaces (incl. PON ports and ONU logical "
                                             "interfaces) discovered from ifDescr."})
    protos = [
        ("Admin status", "if.admin[{#SNMPINDEX}]", "if.admin", "", 3, None),
        ("Oper status", "if.oper[{#SNMPINDEX}]", "if.oper", "", 3, None),
        ("Speed", "if.speed[{#SNMPINDEX}]", "if.speed", "bps", 3, None),
        ("In errors", "if.inerrors[{#SNMPINDEX}]", "if.inerrors", "", 3, None),
        ("Out errors", "if.outerrors[{#SNMPINDEX}]", "if.outerrors", "", 3, None),
        ("In octets", "if.inoctets[{#SNMPINDEX}]", "if.inoctets", "B", 3, None),
        ("Out octets", "if.outoctets[{#SNMPINDEX}]", "if.outoctets", "B", 3, None),
        ("In traffic", "if.inbps[{#SNMPINDEX}]", "if.inoctets", "bps", 0, [pp(10, ""), pp(1, "8")]),
        ("Out traffic", "if.outbps[{#SNMPINDEX}]", "if.outoctets", "bps", 0, [pp(10, ""), pp(1, "8")]),
    ]
    for label, key, mk, units, vt, extra in protos:
        pre = [pp(21, JS_EXTRACT), pp(14, INT_RE, eh="1")]
        if extra:
            pre += extra
        s = {"name": f"Interface [{{#SNMPVALUE}}] {label}", "key_": key, "type": 18, "delay": "0",
             "master_itemid": master(tid, mk), "value_type": vt, "units": units,
             "preprocessing": pre, "tags": if_tags}
        _, new = proto_upsert(lld, s)
        print(f"  {'+' if new else '='} {key}")
    trig_upsert(lld, {"description": "[{#SNMPVALUE}] port is down", "priority": 3,
                      "expression": f"last(/{tpl_host}/if.admin[{{#SNMPINDEX}}]) = 1 and "
                                    f"last(/{tpl_host}/if.oper[{{#SNMPINDEX}}]) = 2",
                      "recovery_mode": 1,
                      "recovery_expression": f"last(/{tpl_host}/if.oper[{{#SNMPINDEX}}]) = 1",
                      "tags": if_tags})
    for what in ("in", "out"):
        trig_upsert(lld, {"description": f"[{{#SNMPVALUE}}] {what}put errors detected", "priority": 2,
                          "expression": f"change(/{tpl_host}/if.{what}errors[{{#SNMPINDEX}}]) > 0",
                          "recovery_mode": 1,
                          "recovery_expression": f"change(/{tpl_host}/if.{what}errors[{{#SNMPINDEX}}]) = 0",
                          "tags": if_tags})
    return lld



GR = ".1.3.6.1.4.1.34592.1.3.4.1.1"


def gateray_system(tid):
    extra = [
        ("CPU load", "system.cpu.load", ".1.3.6.1.4.1.34592.1.3.1.1.8.0", 3, "5m", "%"),
        ("Chassis temperature", "system.temp", ".1.3.6.1.4.1.34592.1.3.1.3.4.0", 3, "5m", "C"),
        ("Alarm status", "system.alarm", ".1.3.6.1.4.1.34592.1.3.1.1.7.0", 1, "5m", None),
    ]
    system_items(tid, extra)


def gateray_onu(tid, tpl_host):
    print("\n=== Gateray: ONU masters ===")
    walks = [
        ("gas.onu.mac", "ONU MAC (walk)", f"{GR}.7.1", "magic", "5m"),
        ("gas.onu.name", "ONU description (walk)", f"{GR}.4.1", "str", "5m"),
        ("gas.onu.state", "ONU state (walk)", f"{GR}.11.1", "plain", "1m"),
        ("gas.onu.dist", "ONU distance (walk)", f"{GR}.13.1", "plain", "5m"),
        ("gas.onu.rx", "ONU Rx raw (walk)", f"{GR}.36.1", "plain", "1m"),
        ("gas.onu.tx", "ONU Tx raw (walk)", f"{GR}.37.1", "plain", "1m"),
        ("gas.onu.volt", "ONU voltage raw (walk)", f"{GR}.38.1", "plain", "5m"),
        ("gas.onu.bias", "ONU bias raw (walk)", f"{GR}.39.1", "plain", "5m"),
        ("gas.onu.temp", "ONU temperature raw (walk)", f"{GR}.40.1", "plain", "5m"),
    ]
    for key, name, oid, mode, delay in walks:
        s = {"name": name, "key_": key, "type": 20, "delay": delay, "snmp_oid": f"walk[{oid}]",
             "value_type": 4, "preprocessing": [pp(21, gr_js(oid, mode))],
             "description": f"SNMP walk {oid}; JSON [{{idx,val}}] keyed as <PON>_<ONU> for LLD recursion.",
             "tags": [{"tag": "scope", "value": "onu"}]}
        _, new = item_upsert(tid, s, update_preproc=True, update_oid=True)
        print(f"  {'+' if new else '='} {key}")
    keep = [w[0] for w in walks]
    for it in api("item.get", {"output": ["itemid", "key_"], "templateids": tid}):
        if it["key_"].startswith("gas.onu.") and it["key_"] not in keep:
            api("item.delete", [it["itemid"]])
            print(f"  - removed obsolete master {it['key_']}")

    print("\n=== Gateray: ONU LLD ===")
    lld, _ = lld_upsert(tid, {"name": "ONU discovery", "key_": "gas.onu.lld", "type": 18,
                              "master_itemid": master(tid, "gas.onu.mac"), "delay": "0", "lifetime": "14d",
                              "description": "ONUs discovered from the MAC table "
                                             "(.1.3.6.1.4.1.34592.1.3.4.1.1.7.1); the index is <PON>_<ONU>"})
    onu_tags = [{"tag": "scope", "value": "onu"}, {"tag": "component", "value": "gateray"},
                {"tag": "pon", "value": "{#PON}"}, {"tag": "onu", "value": "{#ONU}"}]
    protos = [
        ("Description", "gas.onu.name[{#SNMPINDEX}]", "gas.onu.name", "", 4, None, None),
        ("Status (2=Offline, 3=Online)", "gas.onu.state[{#SNMPINDEX}]", "gas.onu.state", "", 3, INT_RE, None),
        ("Distance", "gas.onu.dist[{#SNMPINDEX}]", "gas.onu.dist", "m", 3, INT_RE, None),
        ("Rx power", "gas.onu.rx[{#SNMPINDEX}]", "gas.onu.rx", "dBm", 0, NUM_RE,
         [pp(21, gr_js_value("dbm")), pp(13, "-50\n12", eh="1")]),
        ("Tx power", "gas.onu.tx[{#SNMPINDEX}]", "gas.onu.tx", "dBm", 0, NUM_RE,
         [pp(21, gr_js_value("dbm")), pp(13, "-50\n12", eh="1")]),
        ("Voltage", "gas.onu.volt[{#SNMPINDEX}]", "gas.onu.volt", "V", 0, NUM_RE,
         [pp(21, gr_js_value("volt")), pp(13, "0\n5", eh="1")]),
        ("Bias current", "gas.onu.bias[{#SNMPINDEX}]", "gas.onu.bias", "mA", 0, NUM_RE,
         [pp(21, gr_js_value("bias")), pp(13, "0\n100", eh="1")]),
        ("Temperature", "gas.onu.temp[{#SNMPINDEX}]", "gas.onu.temp", "C", 0, NUM_RE,
         [pp(21, gr_js_value("temp")), pp(13, "-40\n120", eh="1")]),
    ]
    for label, key, mk, units, vt, num_re, extra in protos:
        pre = [pp(21, JS_EXTRACT)]
        if num_re:
            pre.append(pp(14, num_re, eh="1"))
        if extra:
            pre += extra
        s = {"name": f"ONU [PON {{#PON}}/{{#ONU}}] {{#SNMPVALUE}} {label}", "key_": key, "type": 18,
             "delay": "0", "master_itemid": master(tid, mk), "value_type": vt, "units": units,
             "preprocessing": pre, "tags": onu_tags}
        _, new = proto_upsert(lld, s)
        print(f"  {'+' if new else '='} {key}")
    keep_protos = [p[1].split("[")[0] for p in protos] + ["gas.onu.online", "gas.onu.offline"]
    for p in api("itemprototype.get", {"output": ["itemid", "key_"], "discoveryids": lld}):
        if p["key_"].split("[")[0] not in keep_protos:
            api("itemprototype.delete", [p["itemid"]])
            print(f"  - removed obsolete prototype {p['key_']}")

    for key, label, want in (("gas.onu.online[{#SNMPINDEX}]", "Online flag", "3"),
                             ("gas.onu.offline[{#SNMPINDEX}]", "Offline flag", "2")):
        js_flag = ('var id = "{#SNMPINDEX}".replace(/^#/, "");\n'
                   'var data = JSON.parse(value);\n'
                   'for (var i = 0; i < data.length; i++) {\n'
                   '    if (data[i].idx === id) { return (data[i].val === "' + want + '") ? 1 : 0; }\n'
                   '}\nreturn 0;')
        s = {"name": f"ONU [{{#SNMPVALUE}}] {label}", "key_": key, "type": 18, "delay": "0",
             "master_itemid": master(tid, "gas.onu.state"), "value_type": 3,
             "preprocessing": [pp(21, js_flag)], "tags": onu_tags}
        proto_upsert(lld, s)
        print(f"  flag {key}")

    for key, label, flag in (("gas.epon.total.online", "Total ONUs online", "gas.onu.online"),
                             ("gas.epon.total.offline", "Total ONUs offline", "gas.onu.offline")):
        s = {"name": label, "key_": key, "type": 15, "delay": "1m", "value_type": 3,
             "params": f"sum(last_foreach(//{flag}[*]))",
             "preprocessing": [pp(26, "-1", eh="2", ehp="0")],
             "description": f"Calculated: sum(last_foreach(//{flag}[*]))"}
        _, new = item_upsert(tid, s)
        print(f"  {'+' if new else '='} {key}")

    trig_upsert(lld, {"description": "ONU [{#SNMPVALUE}] (PON {#PON}/{#ONU}) offline", "priority": 3,
                      "expression": f"last(/{tpl_host}/gas.onu.state[{{#SNMPINDEX}}]) <> 3",
                      "recovery_mode": 1,
                      "recovery_expression": f"last(/{tpl_host}/gas.onu.state[{{#SNMPINDEX}}]) = 3",
                      "tags": onu_tags})
    st = f"last(/{tpl_host}/gas.onu.state[{{#SNMPINDEX}}]) = 3"
    st_off = f"last(/{tpl_host}/gas.onu.state[{{#SNMPINDEX}}]) <> 3"
    tx = f"last(/{tpl_host}/gas.onu.tx[{{#SNMPINDEX}}])"
    rx = f"last(/{tpl_host}/gas.onu.rx[{{#SNMPINDEX}}])"
    tp = f"last(/{tpl_host}/gas.onu.temp[{{#SNMPINDEX}}])"
    trig_upsert(lld, {"description": "ONU [{#SNMPVALUE}] Tx power out of range", "priority": 2,
                      "expression": f"{st} and ({tx} < " + "{$GATERAY.ONU.TX.MIN} or " +
                                    f"{tx} > " + "{$GATERAY.ONU.TX.MAX})",
                      "recovery_mode": 1,
                      "recovery_expression": f"{st_off} or ({tx} >= " + "{$GATERAY.ONU.TX.MIN} and " +
                                             f"{tx} <= " + "{$GATERAY.ONU.TX.MAX})",
                      "tags": onu_tags})
    trig_upsert(lld, {"description": "ONU [{#SNMPVALUE}] Rx power low", "priority": 2,
                      "expression": f"{st} and {rx} < " + "{$GATERAY.ONU.RX.MIN}",
                      "recovery_mode": 1,
                      "recovery_expression": f"{st_off} or {rx} >= " + "{$GATERAY.ONU.RX.MIN}",
                      "tags": onu_tags})
    trig_upsert(lld, {"description": "ONU [{#SNMPVALUE}] temperature high", "priority": 2,
                      "expression": f"{st} and {tp} > " + "{$GATERAY.ONU.TEMP.MAX}",
                      "recovery_mode": 1,
                      "recovery_expression": f"{st_off} or {tp} <= " + "{$GATERAY.ONU.TEMP.MAX}",
                      "tags": onu_tags})



GATERAY_DESC = """Gateray GR-EP-OLT (EPON-1U8P / EPON-1U4P) - EPON OLT monitoring via SNMP.

Data (enterprise OID .1.3.6.1.4.1.34592):
  * system: name/descr/uptime/location/contact, CPU load, chassis temperature, alarm string
  * interfaces (IF-MIB): admin/oper, speed, in/out octets, in/out traffic (bps), in/out errors,
    tags: interface=<name>, if_type=<GE|PON>
  * ONU LLD from the MAC table (.34592.1.3.4.1.1.7.1). Tables are indexed <PON>.<ONU>, so the
    LLD index/macros are {#SNMPINDEX}=<PON>_<ONU>, {#PON}, {#ONU}, {#SNMPVALUE}=MAC.
    Per ONU: description (.4, empty -> "<unnamed>"), state (.11, 2=Offline 3=Online),
    distance (.13, m), Rx power (.36), Tx power (.37), module voltage (.38),
    bias current (.39), temperature (.40).
  * totals: Total ONUs online / offline

Value decoding (verified against `show olt <n> optical-online-onu` and the NMS ONU table):
  * Rx/Tx power: raw value is optical power in 0.1 uW  ->  dBm = 10*log10(raw/10000)
  * voltage: raw/10000 V | bias: raw/500 mA | temperature: raw/256 C
  * raw 0 / sentinel values are discarded (item becomes unsupported instead of a bogus value)

Thresholds: {$GATERAY.ONU.RX.MIN}, {$GATERAY.ONU.TX.MIN}, {$GATERAY.ONU.TX.MAX},
{$GATERAY.ONU.TEMP.MAX}.
"""

BDCOM3310B_DESC = """BDCOM P3310B EPON OLT (firmware 10.1.0B) - SNMP monitoring.

This firmware does not expose the EPON ONU MIB (ONU names / optical power) via SNMP, so
monitoring covers:
  * system: name/descr/uptime/location/contact
  * interfaces (IF-MIB): uplinks, PON ports (EPON0/x) and ONU logical interfaces (EPON0/x:y) -
    admin/oper status (subscriber online/offline), speed, in/out octets,
    in/out traffic (bps), in/out errors; tags: interface=<name>, if_type=<EPON|GigaEthernet>
ONU optical parameters (Rx/Tx) are NOT available via SNMP on this model/firmware.
"""


def build_gateray():
    global TPL_ID
    tid, new = tpl_get_or_create("Gateray_GR-EP-OLT_EPON_OLT", "Gateray GR-EP-OLT EPON OLT", "OLT")
    TPL_ID = tid
    print(f"Template {'created' if new else 'exists'}: Gateray_GR-EP-OLT_EPON_OLT (id={tid})")
    api("template.update", {"templateid": tid, "description": GATERAY_DESC})
    for m, v, d in (("{$GATERAY.ONU.RX.MIN}", "-27", "ONU Rx power low threshold, dBm"),
                    ("{$GATERAY.ONU.TX.MIN}", "0.5", "ONU Tx power low threshold, dBm"),
                    ("{$GATERAY.ONU.TX.MAX}", "5", "ONU Tx power high threshold, dBm"),
                    ("{$GATERAY.ONU.TEMP.MAX}", "70", "ONU module temperature high threshold, C")):
        macro_upsert(tid, m, v, d)
    for m in ("{$GATERAY.ONU.TX.SCALE}", "{$GATERAY.ONU.RX.SCALE}", "{$GATERAY.ONU.RX.OFFSET}"):
        for mm in api("usermacro.get", {"hostids": tid, "filter": {"macro": m}}):
            api("usermacro.delete", [mm["hostmacroid"]])
            print(f"  - removed obsolete macro {m}")
    gateray_system(tid)
    interface_masters(tid, "if")
    if_tags = [{"tag": "scope", "value": "port"}, {"tag": "component", "value": "gateray"},
               {"tag": "interface", "value": "{#SNMPVALUE}"}, {"tag": "ifindex", "value": "{#SNMPINDEX}"},
               {"tag": "if_type", "value": "{#IF_TYPE}"}]
    iface_lld(tid, "Gateray_GR-EP-OLT_EPON_OLT", if_tags)
    gateray_onu(tid, "Gateray_GR-EP-OLT_EPON_OLT")
    link_to_host(tid)


def build_bdcom_p3310b():
    global TPL_ID
    tid, new = tpl_get_or_create("BDCOM_P3310B_EPON_OLT", "BDCOM P3310B EPON OLT", "OLT")
    TPL_ID = tid
    print(f"Template {'created' if new else 'exists'}: BDCOM_P3310B_EPON_OLT (id={tid})")
    api("template.update", {"templateid": tid, "description": BDCOM3310B_DESC})
    system_items(tid, [])
    interface_masters(tid, "if")
    if_tags = [{"tag": "scope", "value": "port"}, {"tag": "component", "value": "bdcom"},
               {"tag": "interface", "value": "{#SNMPVALUE}"}, {"tag": "ifindex", "value": "{#SNMPINDEX}"},
               {"tag": "if_type", "value": "{#IF_TYPE}"}]
    iface_lld(tid, "BDCOM_P3310B_EPON_OLT", if_tags)
    link_to_host(tid)


def main():
    build_gateray()
    build_bdcom_p3310b()


if __name__ == "__main__":
    main()

