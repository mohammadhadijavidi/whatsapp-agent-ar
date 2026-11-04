FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[prod]"
ENV WA_DB_PATH=/data/whatsapp_agent.db
VOLUME ["/data"]
EXPOSE 8000
# One worker (SQLite), several threads. Put HTTPS (Caddy, nginx, Cloudflare Tunnel) in front.
CMD ["gunicorn", "whatsapp_agent_ar.server:create_app()", "-b", "0.0.0.0:8000", "-w", "1", "--threads", "8", "--access-logfile", "-"]
