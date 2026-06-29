# Container image for GMI AgentBox (GMI CE / hosted path).
# AgentBox maps external 443 -> internal 8080 and injects GMI_MAAS_API_KEY /
# GMI_MAAS_BASE_URL at runtime (read by src/auditor/config.py).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    PORT=8080 \
    HOST=0.0.0.0

WORKDIR /app

# Dependencies first for layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY src/ ./src/
COPY web/ ./web/
COPY data/ ./data/
COPY agentbox.yaml ./

# Run as a non-root user (marketplace safety expectation).
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

# Lightweight liveness probe against the API.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/api/health', timeout=4)" || exit 1

CMD ["python", "-m", "web.server"]
