FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir pydantic fastapi uvicorn

COPY agent_market/ agent_market/
COPY agents/ agents/
COPY agent.json .
COPY agent_log.json .

ENV ROLE=validator
ENV PORT=8000
ENV AGENT_ID=agent-001
ENV STRATEGY=default
ENV VALIDATOR_URL=

EXPOSE ${PORT}

# Start script that runs validator or miner based on ROLE env var
CMD python -c "\
import os, subprocess, sys;\
role = os.environ.get('ROLE', 'validator');\
port = os.environ.get('PORT', '8000');\
agent_id = os.environ.get('AGENT_ID', 'agent-001');\
strategy = os.environ.get('STRATEGY', 'default');\
validator_url = os.environ.get('VALIDATOR_URL', '');\
if role == 'miner':\
    cmd = [sys.executable, '-m', 'agents.miner_agent', '--port', port, '--agent-id', agent_id, '--strategy', strategy, '--host', '0.0.0.0'];\
else:\
    cmd = ['uvicorn', 'agent_market.api.server:app', '--host', '0.0.0.0', '--port', port];\
print(f'Starting as {role}: {\" \".join(cmd)}');\
subprocess.run(cmd)\
"
