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

# Logging
LOG_LEVELS = {"ERROR": 0, "INFO": 1, "DEBUG": 2}
LOG_LEVEL = LOG_LEVELS.get(str(opts.get("log_level", "INFO")).upper(), 1)

def log(level: str, msg: str):
    if LOG_LEVELS[level] <= LOG_LEVEL:
        print(f"[{level}] {msg}", flush=True)

# Global NVL defaults
GLOBAL_ENDIANNESS = opts.get("endianness", "little").lower()
GLOBAL_HEADER_LEN = int(opts.get("header_bytes", 20))  # default 20, Spec header is 20

# COB-ID field extraction (primitive options, keep flexible)
COB_OFFSET        = int(opts.get("cob_id_offset", 8))
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

def build_var_topic(nvl: Dict[str, Any], var: Dict[str, Any]) -> str:
    if "topic" in var and var["topic"]:
        return var["topic"]
    return f"{MQTT_TOPIC_BASE}/{nvl['topic_prefix']}/{var['name']}"

# ---------- Load NVLs and Port ----------
def load_nvls_and_port() -> Tuple[int, List[Dict[str, Any]]]:
    """Lädt Port und NVL-Definitionen aus nvls.json."""
    port = 1202
    nvls: List[Dict[str, Any]] = []
    if NVLS_FILE and os.path.exists(NVLS_FILE):
        with open(NVLS_FILE, "r") as f:
            data = json.load(f)
        port = int(data.get("port", port))
        nvls = data.get("nvls", [])
    else:
        nvls = opts.get("nvls", [])
    return port, nvls

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
            if "scale" not in v:
                v["scale"] = 1.0
            if "precision" in v and v["precision"] is not None:
                v["precision"] = int(v["precision"])
    return nvls

# Laden von Port und NVLs
NVL_PORT, NVLS = load_nvls_and_port()
NVLS = validate_nvls(NVLS)
NVL_BY_COB: Dict[int, Dict[str, Any]] = {int(n["cob_id"]): n for n in NVLS}
last_values: Dict[int, List[Any]] = {int(n["cob_id"]): [None] * len(n["vars"]) for n in NVLS}

# ---------- MQTT ----------
def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties=None):
    log("INFO", f"[MQTT] Connected to {MQTT_HOST}:{MQTT_PORT}, reason_code={reason_code}")

def on_disconnect(client: mqtt.Client, userdata, reason_code, properties=None):
    log("INFO", f"[MQTT] Disconnected from {MQTT_HOST}:{MQTT_PORT}, reason_code={reason_code}")

def on_log(client, userdata, level, buf):
    log("DEBUG", f"[MQTT-LOG] {buf}")

client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
if MQTT_USER:
    client.username_pw_set(MQTT_USER, MQTT_PASS)
client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_log = on_log
log("INFO", f"[MQTT] Connecting to {MQTT_HOST}:{MQTT_PORT} as user '{MQTT_USER}' ...")
client.connect(MQTT_HOST, MQTT_PORT, 60)
client.loop_start()

# ---------- UDP ----------
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    # Größerer RX-Puffer für hohe Raten
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)  # 256 KiB
except Exception as e:
    log("ERROR", f"SO_RCVBUF set failed: {e}")

sock.bind(("0.0.0.0", NVL_PORT))
sock.settimeout(5.0)

log("INFO", f"[NVL] Listening on UDP {NVL_PORT} (host network mode)")
log("INFO", f"[NVL] COB field: offset={COB_OFFSET}, size={COB_SIZE}, byteorder={COB_BYTEORDER}")
log("DEBUG", f"[NVL] Global header_bytes={GLOBAL_HEADER_LEN}, endianness={GLOBAL_ENDIANNESS}")
log("INFO", f"[NVL] NVLs loaded: {[ (n['name'], n['cob_id'], n['topic_prefix']) for n in NVLS ]}")

# ---------- Spec constants (per PDF 2.4.1) ----------
MIN_HEADER_LEN = 20
IDENTITY = bytes((ord('0'), ord('_'), ord('S'), ord('3')))  # b"0_S3"

def parse_header(data: bytes) -> Optional[Dict[str, int]]:
    """Sanity checks + parse fixed header fields; returns dict or None on error."""
    if len(data) < MIN_HEADER_LEN:
        log("ERROR", f"Paket zu kurz: {len(data)} Bytes (< {MIN_HEADER_LEN})")
        return None

    if data[0:4] != IDENTITY:
        # Nicht abbrechen, aber melden und weiter verarbeiten (manche Stacks können abweichen)
        log("DEBUG", f"Unerwartete Identity: {data[0:4]!r}")

    msg_type = int.from_bytes(data[4:8], byteorder="little", signed=False)
    if msg_type != 0:
        # SDO/Diagnose oder anderes – wir verarbeiten nur PDO (0)
        log("DEBUG", f"Ignoriere Nicht-PDO msg_type={msg_type}")
        return None

    cob_idx = int.from_bytes(data[8:10], byteorder="little", signed=False)
    sub_idx = int.from_bytes(data[10:12], byteorder="little", signed=False)
    items   = int.from_bytes(data[12:14], byteorder="little", signed=False)
    total   = int.from_bytes(data[14:16], byteorder="little", signed=False)
    counter = int.from_bytes(data[16:18], byteorder="little", signed=False)
    flags   = data[18]
    chksum  = data[19]

    if total < MIN_HEADER_LEN:
        log("ERROR", f"Unplausible Length-Feld: {total}")
        return None
    if len(data) < total:
        log("ERROR", f"Paket unvollständig: erwartet {total}, erhalten {len(data)}")
        return None

    return {
        "cob_id": cob_idx,
        "sub_index": sub_idx,
        "items": items,
        "total_len": total,
        "counter": counter,
        "flags": flags,
        "checksum": chksum,
    }

def checksum_ok(data: bytes, total_len: int, flags: int, recv_checksum: int) -> bool:
    """Wenn Flag 'Checksum prüfen' gesetzt ist (Bit1), verifiziere Checksum über Data-Bereich."""
    check_requested = (flags & 0b00000010) != 0
    if not check_requested:
        return True
    calc = sum(data[20:total_len]) & 0xFF
    if calc != recv_checksum:
        log("ERROR", f"Checksum-Fehler: recv={recv_checksum}, calc={calc}")
        return False
    return True

def extract_cob_id_flexible(payload: bytes) -> Optional[int]:
    """Weiterhin flexible COB-Extraktion (falls jemand anderes Offset nutzt)."""
    end = COB_OFFSET + COB_SIZE
    if end > len(payload):
        return None
    chunk = payload[COB_OFFSET:end]
    if COB_SIZE == 1:
        return chunk[0]
    return int.from_bytes(chunk, byteorder=COB_BYTEORDER, signed=False)

# ---------- Main loop ----------
while True:
    try:
        data, addr = sock.recvfrom(4096)
        if LOG_LEVEL >= LOG_LEVELS["DEBUG"]:
            log("DEBUG", f"[NVL] Packet from {addr}, len={len(data)}, first bytes: {data[:32].hex(' ')}")
    except socket.timeout:
        continue
    except Exception as e:
        log("ERROR", f"[NVL] Socket error: {e}")
        time.sleep(1.0)
        continue

    if not data:
        continue

    # Header nach Spezifikation prüfen
    hdr = parse_header(data)
    if hdr is None:
        continue

    # Checksumme prüfen (nur wenn angefordert)
    if not checksum_ok(data, hdr["total_len"], hdr["flags"], hdr["checksum"]):
        # Nur protokollieren, keine Werte aktualisieren
        continue

    # COB-ID bestimmen (präferiere Spec-Header, fallback auf flexiblen Weg)
    cob_id = hdr["cob_id"]
    if cob_id is None:
        cob_id = extract_cob_id_flexible(data)
        if cob_id is None:
            log("ERROR", f"[NVL] COB-ID nicht extrahierbar (len={len(data)})")
            continue

    nvl = NVL_BY_COB.get(int(cob_id))
    if not nvl:
        # Unbekannte COB-ID ins eigenes Topic schreiben
        topic = f"{MQTT_TOPIC_BASE}/unknown_cob/{int(cob_id)}"
        payload = {
            "len": len(data),
            "counter": hdr["counter"],
            "flags": hdr["flags"],
            "checksum": hdr["checksum"],
            "data_hex": data[:min(len(data), 256)].hex(),  # begrenze Größe
            "from": f"{addr[0]}:{addr[1]}",
        }
        try:
            client.publish(topic, payload=json.dumps(payload), qos=0, retain=False)
            log("INFO", f"[NVL] Unbekannte COB-ID {cob_id} → {topic}")
        except Exception as e:
            log("ERROR", f"[MQTT] Publish unknown COB-ID error: {e}")
        continue

    # Datenbeginn (per NVL konfigurierbar), Spez-Header ist 20
    header_len = max(20, int(nvl.get("header_bytes", GLOBAL_HEADER_LEN)))
    endianness = nvl.get("endianness", GLOBAL_ENDIANNESS)

    if len(data) < header_len:
        log("ERROR", f"[NVL] Packet too short ({len(data)} bytes) for header_bytes={header_len}, COB-ID={cob_id}")
        continue

    # Optional: Plausibilitätscheck gegen Length-Feld
    if hdr["total_len"] < header_len or len(data) < hdr["total_len"]:
        log("ERROR", f"[NVL] Unplausible total_len={hdr['total_len']} vs header_len={header_len} or len={len(data)}")
        continue

    # Variablen dekodieren
    offset = header_len
    out_vals: List[Any] = []
    try:
        for var in nvl["vars"]:
            value, size = decode_value(data, offset, var["type"], endianness)
            offset += size
            value = apply_scale_precision(value, var.get("scale", 1.0), var.get("precision", None))
            out_vals.append(value)
    except Exception as e:
        log("ERROR", f"[NVL] Decode error for COB-ID={cob_id} ({nvl['name']}): {e}")
        continue

    # Publish per variable (on change optional) – JSON Payload mit Meta
    lv = last_values[int(cob_id)]
    for i, var in enumerate(nvl["vars"]):
        value = out_vals[i]
        if ON_CHANGE and lv[i] is not None and value == lv[i]:
            continue
        lv[i] = value

        topic = var.get("topic") or f"{MQTT_TOPIC_BASE}/{nvl['topic_prefix']}/{var['name']}"
        payload = {
            "value": value,
        }
        if "unit" in var:
            payload["unit_of_measurement"] = var["unit"]
        if "device_class" in var:
            payload["device_class"] = var["device_class"]

        retain_flag = bool(var.get("retain", RETAIN))  # pro-Variable override
        try:
            client.publish(topic, payload=json.dumps(payload), qos=QOS, retain=retain_flag)
            log("INFO", f"[NVL] {nvl['name']}[{var['name']}]={value} → {topic}")
        except Exception as e:
            log("ERROR", f"[MQTT] Publish error: {e}")
