FROM python:3.11-alpine
WORKDIR /app

# Abhängigkeiten installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


COPY listener.py /app/listener.py
COPY run.sh /app/run.sh

RUN chmod +x /app/run.sh

EXPOSE 1202/udp
CMD [ "/app/run.sh" ]
