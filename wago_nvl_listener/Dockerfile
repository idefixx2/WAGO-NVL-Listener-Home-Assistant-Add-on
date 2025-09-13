ARG BUILD_FROM=ghcr.io/hassio-addons/base:15.0.5
FROM $BUILD_FROM

LABEL maintainer="you@example.invalid" \
      description="WAGO NVL Listener with multi-COB-ID and MQTT v2"

RUN apk add --no-cache python3 py3-pip
RUN pip3 install --no-cache-dir paho-mqtt==2.1.0

WORKDIR /app
COPY listener.py /app/listener.py
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

CMD ["/app/run.sh"]
