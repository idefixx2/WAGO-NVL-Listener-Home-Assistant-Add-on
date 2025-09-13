#!/usr/bin/env python3
import socket
import struct
import json
import time
import os
import sys
from typing import Dict, Any, List, Optional, Tuple
import paho.mqtt.client as mqtt

# stdout sofort flushen
sys.stdout.reconfigure(line_buffering=True)

OPTIONS_PATH = "/data/options.json"

# ---------- Load options ----------
def load_options() -> Dict[str, Any]:
    with open(OPTIONS_PATH, "r") as f:
        return json.load(f)

opts = load_options()

# MQTT settings
MQTT_HOST         = opts.get("mqtt_host", "core-mosquitto")
MQTT_PORT         = int(opts.get("mqtt_port", 1883))
MQTT_USER         = opts.get("mqtt_user", "")
MQTT_PASS         = opts.get("mqtt_pass", "")
MQTT_TOPIC_BASE   = opts.get("mqtt_topic_base", "wago/nvl")
QOS               = int(opts.get("qos", 0))
RETAIN            = bool(opts.get("retain", False))
ON_CHANGE         = bool(opts.get("on_change", True))

# Global NVL defaults
GLOBAL_ENDIANNESS = opts.get("endianness", "little").lower()
GLOBAL_HEADER_LEN = int(opts.get("header_bytes", 16))

# UDP settings
NVL_PORT          = int(opts.get("nvl_port", 1202))

# COB-ID field extraction (primitive options)
COB_OFFSET        = int(opts.get("cob_id_offset", 0))
COB_SIZE          = int(opts.get("cob_id_size", 2))
COB_BYTEORDER     = str(opts.get("cob_id_byteorder", "little")).lower()

# NVL definitions file
NVLS_FILE         = opts.get("nvls_file", "/config/wago_nvl/nvls.json")

# ---------- Validation ----------
def _validate_endianness(e: str) -> str:
    if e not in ("little", "big"):
        raise ValueError("endianness must be 'little' or 'big'")
    return e

GLOBAL_ENDIANNESS = _validate_endianness(GLOBAL_ENDIANNESS)
COB_BYTEORDER = _validate_endianness(COB_BYTEORDER)
if COB_SIZE not in (1, 2, 4):
    raise ValueError("cob_id_size must be 1, 2 or 4")

# Supported data types: (struct code, size, to_python)
TYPE_MAP: Dict[str, Tuple[str, int, Any]] = {
    "BOOL":  ("B", 1, lambda x: bool(x)),
    "SINT":  ("b", 1, int),
    "USINT": ("B", 1, int),
    "BYTE":  ("B", 1, int),
    "INT":   ("h", 2, int),
    "UINT":  ("H", 2, int),
    "WORD":  ("H", 2, int),
    "DINT":  ("i", 4, int),
    "UDINT": ("I", 4, int),
    "REAL":  ("f", 4, float),
    "LREAL": ("d", 8, float),
}

def fmt_end(prefix: str, endianness: str) -> str:
    return (">" if endianness == "big" else "<") + prefix

def decode_value(payload: bytes, offset: int, vtype: str, endianness: str) -> Tuple[Any, int]:
    fmtcode, size, caster = TYPE_MAP[vtype]
    if offset + size > len(payload):
        raise ValueError("Packet too short for declared variables")
    raw = struct.unpack(fmt_end(fmtcode, endianness), payload[offset:offset+size])[0]
    return caster(raw), size

def apply_scale_precision(val: Any, scale: float, precision: Optional[int]) -> Any:
    if isinstance(val, (int, float)):
        val = val * float(scale)
        if precision is not None:
            val = round(val, int(precision))
    return val

def extract_cob_id(payload: bytes) -> Optional[int]:
    end = COB_OFFSET + COB_SIZE
    if end > len(payload):
        return None
    chunk = payload[COB_OFFSET:end]
    if COB_SIZE == 1:
        return chunk[0]
    return int.from_bytes(chunk, byteorder=COB_BYTEORDER, signed=False)

def build_var_topic(nvl: Dict[str, Any], var: Dict[str, Any]) -> str:
    if "topic" in var and var["topic"]:
        return var["topic"]
    return f"{MQTT_TOPIC_BASE}/{nvl['topic_prefix']}/{var['name']}"

def load_nvls() -> List[Dict[str, Any]]:
    if NVLS_FILE and os.path.exists(NVLS_FILE):
        with open(NVLS_FILE, "r") as f:
            data = json.load(f)
        nvls = data.get("nvls", [])
    else:
        nvls = opts.get("nvls", [])
    return nvls

def validate_nvls(nvls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    for nvl in nvls:
        name = nvl.get("name")
        if not name:
            raise ValueError("Each NVL requires a 'name'")
        cob_id = nvl.get("cob_id")
        if cob_id is None:
            raise ValueError(f"NVL '{name}': missing 'cob_id'")
        if cob_id in seen:
            raise ValueError(f"Duplicate cob_id '{cob_id}' in NVLs")
        seen.add(cob_id)

        nvl_end = _validate_endianness(nvl.get("endianness", GLOBAL_ENDIANNESS).lower())
        nvl["endianness"] = nvl_end
        nvl["header_bytes"] = int(nvl.get("header_bytes", GLOBAL_HEADER_LEN))
        topic_prefix = nvl.get("topic_prefix", name)
        nvl["topic_prefix"] = topic_prefix

        vars_ = nvl.get("vars", [])
        if not isinstance(vars_, list) or not vars_:
            raise ValueError(f"NVL '{name}': 'vars' must be a non-empty list")

        for v in vars_:
            vname = v.get("name")
            vtype = str(v.get("type", "")).upper()
            if not vname:
                raise ValueError(f"NVL '{name}': variable ohne 'name'")
            if vtype not in TYPE_MAP:
                raise ValueError(f"NVL '{name}': unsupported type '{vtype}' for var '{vname}'")
            v["type"] = vtype
            if "scale" not in v: v["scale"] = 1.0
            if "precision" in v and v["precision"] is not None:
                v["precision"] = int(v["precision"])
    return nvls

NVLS = validate_nvls(load_nvls())
NVL_BY_COB: Dict[int, Dict[str, Any]] = { int(n["cob_id"]): n for n in NVLS }
last_values: Dict[int, List[Any]] = { int(n["cob_id"]): [None] * len(n["vars"]) for n in NVLS }

# ---------- MQTT (Paho v2) ----------
def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties=None):
    print(f"[MQTT] Connected to {MQTT_HOST}:{MQTT_PORT}, reason_code={reason_code}", flush=True)

def on_disconnect(client: mqtt.Client, userdata, reason_code, properties=None):
    print(f"[MQTT] Disconnected from {MQTT_HOST}:{MQTT_PORT}, reason_code={reason_code}", flush=True)

def on_log(client, userdata, level, buf):
    print(f"[MQTT-LOG] {buf}", flush=True)

client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
if MQTT_USER:
    client.username_pw_set(MQTT_USER, MQTT_PASS)
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_log = on_log
print(f"[MQTT] Connecting to {MQTT_HOST}:{MQTT_PORT} as user '{MQTT_USER}' ...", flush=True)
print("[MQTT] Vor connect()", flush=True)
client.connect(MQTT_HOST, MQTT_PORT, 60)
print("[MQTT] Nach connect()", flush=True)
client.loop_start()

# ---------- UDP ----------
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", NVL_PORT))
sock.settimeout(5.0)

print(f"[NVL] Listening on UDP {NVL_PORT}", flush=True)
print(f"[NVL] COB field: offset={COB_OFFSET}, size={COB_SIZE}, byteorder={COB_BYTEORDER}", flush=True)
print(f"[NVL] Global header_bytes={GLOBAL_HEADER_LEN}, endianness={GLOBAL_ENDIANNESS}", flush=True)
print(f"[NVL] NVLs loaded: {[ (n['name'], n['cob_id'], n['topic_prefix']) for n in NVLS ]}", flush=True)

# ---------- Main loop ----------
while True:
    try:
        data, addr = sock.recvfrom(4096)
    except socket.timeout:
        continue
    except Exception as e:
        print(f"[NVL] Socket error: {e}", flush=True)
        time.sleep(1.0)
        continue

    if not data:
        continue

    cob_id = extract_cob_id(data)
    if cob_id is None:
        print(f"[NVL] Packet too short for COB-ID extraction (len={len(data)})", flush=True)
        continue

    nvl = NVL_BY_COB.get(int(cob_id))
    if not nvl:
        print(f"[NVL] Ignored packet with unknown COB-ID={cob_id} from {addr}", flush=True)
        continue

    header_len = int(nvl.get("header_bytes", GLOBAL_HEADER_LEN))
    endianness = nvl.get("endianness", GLOBAL_ENDIANNESS)

    if len(data) < header_len:
        print(f"[NVL] Packet too short ({len(data)} bytes) for header_bytes={header_len}, COB-ID={cob_id}", flush=True)
        continue

    offset = header_len
    out_vals: List[Any] = []
    try:
        for var in nvl["vars"]:
            value, size = decode_value(data, offset, var["type"], endianness)
            offset += size
            value = apply_scale_precision(value, var.get("scale", 1.0), var.get("precision", None))
            out_vals.append(value)
    except Exception as e:
        print(f"[NVL] Decode error for COB-ID={cob_id} ({nvl['name']}): {e}", flush=True)
        continue

    # Publish per variable
    lv = last_values[int(cob_id)]
    for i, var in enumerate(nvl["vars"]):
        value = out_vals[i]
        if ON_CHANGE and lv[i] is not None and value == lv[i]:
            continue
        lv[i] = value
        topic = var.get("topic") or f"{MQTT_TOPIC_BASE}/{nvl['topic_prefix']}/{var['name']}"
        try:
            client.publish(topic, payload=value, qos=QOS, retain=RETAIN)
            print(f"[NVL] {nvl['name']}[{var['name']}]={value} → {topic}", flush=True)
        except Exception as e:
            print(f"[MQTT] Publish error: {e}", flush=True)
