FROM ghcr.io/home-assistant/aarch64-base:latest

RUN apk add --no-cache python3 py3-pip
RUN python3 -m venv /venv
ENV PATH="/venv/bin:$PATH"
RUN pip install --no-cache-dir paho-mqtt==2.1.0

WORKDIR /app
COPY listener.py /app/listener.py
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

CMD ["/app/run.sh"]
