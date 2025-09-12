# WAGO NVL Listener (Home Assistant Add-on)

This add-on receives CODESYS Network Variable List (NVL) UDP packets (e.g., from a WAGO 750-841) and publishes the values in MQTT topics. Home Assistant can integrate these topics as sensors—without Modbus polling and with minimal PLC load.

## Features
- UDP listener for NVL packets
- Configurable variable order, data types, and MQTT topics
- Big/little endian selectable (default: big)
- Optional scaling, precision, QoS, retain
- Duplicate suppression (on_change) for load reduction

## Installation
1. Add this repository to Home Assistant:
   - Settings → Add-ons → Add-on Store → Three-dot menu → Repositories → Enter the URL of this repository.
2. Install the “WAGO NVL Listener” add-on.
3. Provide an MQTT broker (e.g., core-mosquitto) and set the access data in the add-on options.
4. Start the add-on and check the logs.

## WAGO/CODESYS setup (short)
- Create a network variable list (publisher) in CODESYS 2.3:
  - Transport: UDP
  - Target IP: IP of your Home Assistant
  - Target port: 1202 (default for the add-on; can be customized via port mapping)
  - Configure the order and data types of the NVL variables exactly as specified in the add-on options (“vars”).
- Transmission cycle, e.g., 200 ms or “on change.”

## Home Assistant: MQTT Sensors
Example:
```yaml
mqtt:
  sensor:
    - name: "Raumtemperatur Ist"
      state_topic: "wago/raumtemp/ist"
      unit_of_measurement: "°C"
      device_class: temperature
    - name: "Licht Status"
      state_topic: "wago/licht/status"
      value_template: "{{ value | int }}"
