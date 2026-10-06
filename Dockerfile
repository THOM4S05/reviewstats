FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml requirements-lock.txt README.md ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN python -m pip install --no-cache-dir -c requirements-lock.txt . \
    && useradd --create-home appuser \
    && mkdir /data && chown appuser:appuser /data
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log --log-level info"]
