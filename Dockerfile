FROM python:3.11-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_DIR=/app \
    APP_DATA_DIR=/data \
    PORT=80

RUN apk add --no-cache su-exec sqlite-libs sqlite-dev build-base libcap \
    && setcap 'cap_net_bind_service=+ep' /usr/local/bin/python3

WORKDIR $APP_DIR
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY entrypoint.sh ./

EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "app.main"]
