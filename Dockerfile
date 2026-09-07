FROM python:3.12-slim

WORKDIR /app

COPY . .

ENV HOST=0.0.0.0 \
    PORT=8765

EXPOSE 8765

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8765/api/status')"

CMD ["python", "run_game.py", "--no-browser"]