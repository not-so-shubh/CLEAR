FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

COPY ui ./ui

USER 65532:65532

EXPOSE 8765

CMD ["python", "-m", "ui.public_demo"]
