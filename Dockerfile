FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

ENV DB_PATH=/data/agente.db
VOLUME /data

EXPOSE 8000
CMD ["uvicorn", "agente_compras.web:app", "--host", "0.0.0.0", "--port", "8000"]
