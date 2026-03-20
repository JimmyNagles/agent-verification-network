FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir pydantic fastapi uvicorn

COPY agent_market/ agent_market/
COPY agents/ agents/
COPY agent.json .
COPY agent_log.json .

EXPOSE 8000

CMD ["uvicorn", "agent_market.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
