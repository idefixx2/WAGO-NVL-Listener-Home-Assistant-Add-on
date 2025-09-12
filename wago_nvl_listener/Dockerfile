FROM python:3.11-alpine
WORKDIR /app
COPY listener.py run.sh /app/
RUN pip install --no-cache-dir paho-mqtt
RUN chmod +x /app/run.sh
CMD ["/app/run.sh"]
