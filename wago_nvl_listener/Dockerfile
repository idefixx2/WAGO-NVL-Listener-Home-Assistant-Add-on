# Basis-Image passend zur Architektur
ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base:latest
FROM $BUILD_FROM

LABEL maintainer="you@example.invalid" \
      description="WAGO NVL Listener with multi-COB-ID and MQTT v2"

# Python + Paho-MQTT direkt aus Alpine-Paketen installieren
RUN apk add --no-cache python3 py3-pip py3-paho-mqtt

# Arbeitsverzeichnis setzen
WORKDIR /app

# Add-on Dateien ins Image kopieren
COPY listener.py /app/listener.py
COPY run.sh /app/run.sh

# Ausführbar machen
RUN chmod +x /app/run.sh

# Startkommando
CMD ["/app/run.sh"]
