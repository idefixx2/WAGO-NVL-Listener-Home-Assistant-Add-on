#!/usr/bin/env python3
import paho.mqtt.client as mqtt
import socket
import struct

# MQTT-Broker-Konfiguration
MQTT_BROKER = "mqtt_broker_adresse"
MQTT_PORT = 1883
MQTT_TOPIC = "wago/nvl"

# Callback: Verbindung hergestellt
def on_connect(client, userdata, flags, reason_code, properties=None):
    print("Verbunden mit MQTT-Broker", reason_code)
    client.subscribe(MQTT_TOPIC)

# Callback: Nachricht empfangen
def on_message(client, userdata, msg):
    print(f"Nachricht empfangen: {msg.topic} -> {msg.payload}")

# UDP-Socket einrichten (Beispiel)
UDP_IP = "0.0.0.0"
UDP_PORT = 1202

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))

# MQTT-Client mit neuer API-Version erstellen
client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.V2)

client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, 60)

print("Starting WAGO NVL Listener...")

# Hauptloop
while True:
    data, addr = sock.recvfrom(1024)
    print(f"Empfangen von {addr}: {data}")
    # Beispiel: Daten an MQTT weiterleiten
    client.publish(MQTT_TOPIC, data)
    client.loop(timeout=1.0)
