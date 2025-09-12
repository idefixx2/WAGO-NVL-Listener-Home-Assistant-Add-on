import socket, struct, json, os, time
import paho.mqtt.client as mqtt

OPTIONS_PATH = "/data/options.json"

def load_options():
    with open(OPTIONS_PATH, "r") as f:
        return json.load(f)

opts = load_options()

MQTT_HOST   = opts.get("mqtt_host", "core-mosquitto")
MQTT_PORT   = int(opts.get("mqtt_port", 1883))
MQTT_USER   = opts.get("mqtt_user", "")
MQTT_PASS   = opts.get("mqtt_pass", "")
ENDIANNESS  = opts.get("endianness", "big").lower()
HEADER_BYTES= int(opts.get("header_bytes", 16))
QOS         = int(opts.get("qos", 0))
RETAIN      = bool(opts.get("retain", False))
ON_CHANGE   = bool(opts.get("on_change", True))
VARS        = opts.get("vars", [])

if ENDIANNESS not in ("big", "little"):
    raise ValueError("endianness must be 'big' or 'little'")

# Struct format helper
def fmt_end(prefix):
    return ">" + prefix if ENDIANNESS == "big" else "<" + prefix

# Supported types and their sizes
TYPE_MAP = {
    "BOOL": ("B", 1, lambda x: 1 if x else 0, lambda b: (b != 0)),
    "BYTE": ("B", 1, int, lambda b: b),
    "WORD": ("H", 2, int, lambda w: w),
    "INT":  ("h", 2, int, lambda h: h),
    "DINT": ("i", 4, int, lambda i: i),
    "REAL": ("f", 4, float, lambda f: f),
    "LREAL":("d", 8, float, lambda d: d),
}

# Sanity check var list
for v in VARS:
    t = v.get("type", "").upper()
    if t not in TYPE_MAP:
        raise ValueError(f"Unsupported type in vars: {t}")
    v["type"] = t
    v.setdefault("scale", 1.0)
    v.setdefault("precision", None)

# MQTT client
client = mqtt.Client()
if MQTT_USER:
    client.username_pw_set(MQTT_USER, MQTT_PASS)
client.connect(MQTT_HOST, MQTT_PORT, 60)
client.loop_start()

# UDP listener
UDP_IP = ""   # all interfaces
UDP_PORT = 1202
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))
sock.settimeout(5.0)

print(f"[NVL] Listening on UDP {UDP_PORT}, header_bytes={HEADER_BYTES}, endianness={ENDIANNESS}")
print(f"[NVL] Variables: {[ (v['name'], v['type'], v['topic']) for v in VARS ]}")

last_values = [None] * len(VARS)

def decode_value(data, offset, vtype):
    fmtcode, size, _, dec = TYPE_MAP[vtype]
    if offset + size > len(data):
        raise ValueError("Packet too short for declared variables")
    raw = struct.unpack(fmt_end(fmtcode), data[offset:offset+size])[0]
    return dec(raw), size

def apply_scale_precision(val, scale, precision):
    val = val * scale
    if precision is not None:
        val = round(val, int(precision))
    return val

while True:
    try:
        data, addr = sock.recvfrom(4096)
    except socket.timeout:
        # idle heartbeat
        continue
    except Exception as e:
        print(f"[NVL] Socket error: {e}")
        time.sleep(1)
        continue

    # Minimal header validation (optional): often 16 bytes header
    if len(data) < HEADER_BYTES:
        print(f"[NVL] Packet too short ({len(data)} bytes), expected >= {HEADER_BYTES}")
        continue

    offset = HEADER_BYTES
    out_vals = []

    try:
        for i, v in enumerate(VARS):
            value, size = decode_value(data, offset, v["type"])
            offset += size
            value = apply_scale_precision(value, v.get("scale", 1.0), v.get("precision", None))
            out_vals.append(value)
    except Exception as e:
        print(f"[NVL] Decode error: {e}")
        continue

    # Publish
    for i, v in enumerate(VARS):
        value = out_vals[i]
        if ON_CHANGE and last_values[i] is not None and value == last_values[i]:
            continue
        last_values[i] = value
        topic = v["topic"]
        client.publish(topic, value, qos=QOS, retain=RETAIN)
        # lightweight log
        print(f"[NVL] {v['name']}={value} → {topic}")
