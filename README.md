# WAGO NVL Listener – Home Assistant Add-on

This Home Assistant add-on listens for **CODESYS Network Variable List (NVL)** UDP telegrams from a WAGO PLC (or other CODESYS-based devices) and publishes the decoded values to MQTT.  
It supports multiple COB-IDs, per-variable scaling and precision, Home Assistant–friendly metadata, and configurable logging.

---

## ✨ Features

- **Host network mode** for direct UDP reception without port mapping.
- **Multiple NVLs** with individual COB-IDs, header lengths, and endianness.
- **Per-variable settings**: scale, precision, unit, device_class, retain.
- **Checksum validation** (only updates MQTT if checksum is correct).
- **Configurable log levels** to control verbosity.
- **Unknown COB-ID handling**: publishes raw packet data to a dedicated MQTT topic.
- **Home Assistant–friendly payloads** for automatic sensor creation.

---

## 📦 Installation

1. Copy the add-on into your Home Assistant `addons` folder or install from the repository.
2. Configure MQTT credentials in the add-on options.
3. Place your nvls.json in /config/wago_nvl/nvls.json.
4. Start the add-on and watch the logs.

⚙️ Configuration
Add-on Options (config.json)
Option	Type	Description
mqtt_host	str	MQTT broker hostname (e.g. core-mosquitto)
mqtt_port	int	MQTT broker port (default: 1883)
mqtt_user	str	MQTT username
mqtt_pass	str	MQTT password
mqtt_topic_base	str	Base topic for all NVL values
qos	int	MQTT QoS level (0, 1, or 2)
retain	bool	Global retain flag (overridden by per-variable retain in nvls.json)
on_change	bool	Publish only when value changes
endianness	str	Default byte order: "little" or "big"
header_bytes	int	Default header length in bytes
cob_id_offset	int	Byte offset of COB-ID in packet
cob_id_size	int	Size of COB-ID field in bytes
cob_id_byteorder	str	Byte order of COB-ID field
nvls_file	str	Path to nvls.json
log_level	str	"DEBUG", "INFO", or "ERROR"

🪵 Log Levels

The log_level option controls verbosity:
* DEBUG – Full packet dumps, detailed parsing info, MQTT logs.
* INFO – Connection status, value updates, unknown COB-ID notices.
* ERROR – Only errors (socket issues, checksum failures, decode errors).

📄 Data Formats
Supported variable types and their decoding:
Type	Struct Code	Size (bytes)	Python Cast
BOOL	"B"	1	lambda x: bool(x)
SINT	"b"	1	int
USINT	"B"	1	int
BYTE	"B"	1	int
INT	"h"	2	int
UINT	"H"	2	int
WORD	"H"	2	int
DINT	"i"	4	int
UDINT	"I"	4	int
REAL	"f"	4	float
LREAL	"d"	8	float

📂 NVL Definition File (nvls.json)

This file defines the UDP port to listen on and the NVLs to decode.
Example:
JSON:
```
{
  "port": 1202,
  "nvls": [
    {
      "name": "NVL_1",
      "cob_id": 385,
      "topic_prefix": "nvl1",
      "header_bytes": 16,
      "endianness": "little",
      "vars": [
        { "name": "Pressure", "type": "REAL", "scale": 1.0, "precision": 2, "unit": "bar", "device_class": "pressure", "retain": true },
        { "name": "Temp", "type": "INT", "scale": 0.1, "precision": 1, "unit": "°C", "device_class": "temperature", "retain": false }
      ]
    },
    {
      "name": "NVL_2",
      "cob_id": 386,
      "topic_prefix": "nvl2",
      "header_bytes": 20,
      "endianness": "little",
      "vars": [
        { "name": "Status", "type": "BOOL", "unit": "", "device_class": "power", "retain": true },
        { "name": "Count", "type": "DINT", "unit": "count", "device_class": "none", "retain": false }
      ]
    }
  ]
}
```

📨 MQTT Publishing

    Topic: <mqtt_topic_base>/<topic_prefix>/<var_name> unless overridden by topic in the variable definition.

    Payload: JSON object containing:
JSON:
```
{
  "value": 23.5,
  "unit_of_measurement": "°C",
  "device_class": "temperature"
}
```

* Retain: Taken from the variable’s retain field; falls back to global retain if not set.
* Unknown COB-IDs: Published to <mqtt_topic_base>/unknown_cob/<cob_id> with raw packet data.

🛡 Error Handling
* Packet length checks before parsing to avoid index errors.
* Checksum validation (if requested by packet flags) before updating MQTT.
* Socket receive buffer increased for high packet rates.

🔍 Home Assistant MQTT Discovery

To have Home Assistant automatically create entities for your NVL variables:

1. Enable MQTT Discovery in Home Assistant:
YAML:
mqtt:
  discovery: true
  discovery_prefix: homeassistant
2. Modify the add-on to publish MQTT Discovery config topics for each variable. For example, for a temperature sensor:
CODE:
homeassistant/sensor/nvl1_temp/config
with payload:
JSON:
```
{
  "name": "NVL1 Temperature",
  "state_topic": "wago/nvl/nvl1/Temp",
  "unit_of_measurement": "°C",
  "device_class": "temperature",
  "unique_id": "nvl1_temp",
  "value_template": "{{ value_json.value }}"
}
3. Restart the add-on or trigger a discovery refresh in Home Assistant.
With this in place, all NVL variables with proper unit and device_class will appear automatically in Home Assistant without manual entity configuration.
```

📌 Notes
* on_change in config.json is global and still active — there is no per-variable override.
* retain in config.json is a fallback; per-variable retain in nvls.json takes precedence.
* Use log_level: "DEBUG" during setup/troubleshooting, then switch to "INFO" or "ERROR" for normal operation.