FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir pydantic fastapi uvicorn web3

COPY agent_market/ agent_market/
COPY agents/ agents/
COPY contracts/deployed.json contracts/deployed.json
COPY contracts/commerce_deployed.json contracts/commerce_deployed.json
COPY contracts/registry_deployed.json contracts/registry_deployed.json
COPY scripts/start.py scripts/start.py
COPY agent.json .
COPY agent_log.json .

EXPOSE 8000

CMD ["python", "scripts/start.py"]
