FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates/ templates/
COPY static/ static/
COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh && \
    useradd -M -d /tmp -s /sbin/nologin appuser && \
    chown -R appuser:appuser /app

ENV APP_PORT=5000 \
    DEBUG=false \
    HOME=/tmp

EXPOSE $APP_PORT

ENTRYPOINT ["/entrypoint.sh"]