# ---- Stage 1: build dependencies into a venv ----
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN python -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --upgrade pip \
    && /venv/bin/pip install --no-cache-dir -r requirements.txt

# ---- Stage 2: runtime ----
FROM python:3.12-slim AS runtime
WORKDIR /app

RUN groupadd -r worker && useradd -r -g worker worker

COPY --from=builder /venv /venv
COPY worker.py operations.py ./

ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER worker

CMD ["python", "worker.py"]
