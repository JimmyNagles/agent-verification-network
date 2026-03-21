# Deploying to EigenCompute (TEE)

Running the validator inside a Trusted Execution Environment (Intel TDX) on EigenCompute means honeypot scoring is cryptographically attested. Nobody can tamper with the results — not even the host machine operator.

## Why TEE Matters

The validator is the one who scores miners. If scoring happens in a TEE:
- Results are cryptographically attested via KMS signing key
- The verifiable build proves deployed code matches the GitHub source
- No one can manipulate honeypot results or fee splits
- Trust is hardware-enforced, not just contract-enforced

## Prerequisites

```bash
# Install ecloud CLI
curl -fsSL https://raw.githubusercontent.com/Layr-Labs/eigencloud-tools/master/install-all.sh | bash

# Authenticate (needs a wallet private key)
ecloud auth login

# Subscribe to billing ($100 free credit for hackathon)
ecloud billing subscribe
```

You also need Sepolia ETH for the deployment transaction (free from faucets):
- https://cloud.google.com/application/web3/faucet/ethereum/sepolia

## Deploy

```bash
# Get your latest commit SHA
COMMIT=$(git rev-parse HEAD)

# Create .env file for the TEE
cat > .env.eigencompute << EOF
PORT=8000
ROLE=validator
AGENT_ID=eigen-validator-001
PRIVATE_KEY=0xYourPrivateKey
USE_LLM=false
EOF

# Deploy with verifiable build
ecloud compute app deploy \
  --verifiable \
  --repo https://github.com/JimmyNagles/agent-verification-network \
  --commit $COMMIT \
  --env-file .env.eigencompute \
  --instance-type g1-standard-4t \
  --log-visibility public \
  --resource-usage-monitoring enable \
  --environment sepolia \
  --name agent-verification-network \
  --skip-profile
```

The build takes ~3 minutes. EigenCompute:
1. Pulls the code from GitHub
2. Builds the Docker image inside their infrastructure
3. Records the build hash on-chain (verifiable)
4. Deploys to an Intel TDX enclave

## Verify

```bash
# Check app status
ecloud compute app info <APP-ID>

# Stream logs
ecloud compute app logs <APP-ID> --watch

# Health check
curl http://<IP>:8000/health
```

## Current Deployment

| Field | Value |
|-------|-------|
| App ID | `0x7Fc30484aCF81961bc766FE07281cf2684A33ffE` |
| IP | `34.142.184.34` |
| Port | `8000` |
| Instance | g1-standard-4t (Intel TDX) |
| Dashboard | [verify-sepolia.eigencloud.xyz](https://verify-sepolia.eigencloud.xyz/app/0x7Fc30484aCF81961bc766FE07281cf2684A33ffE) |
| Health | http://34.142.184.34:8000/health |
| Build | Verifiable, provenance signature on-chain |

## How It Connects

```
EigenCompute TEE (Intel TDX)
  └── Validator API (port 8000)
        ├── /verify → routes to miners, creates jobs on AgenticCommerceV2
        ├── /protocol → returns Base Mainnet contract addresses + ABIs
        ├── /jobs → reads job count from AgenticCommerceV2
        └── /health → service status
              │
              ▼
        Base Mainnet Contracts
        ├── AgenticCommerceV2 (0xE4ED0C73...) — jobs + escrow + fee split
        ├── AgentScorer (0xc1679D1A...) — reputation scores
        ├── MinerRegistry (0xE0d1346b...) — agent discovery
        └── ERC-8004 Registries — official identity + reputation
```

Two validators now run simultaneously:
1. **Railway** — primary, public-facing API
2. **EigenCompute TEE** — cryptographically attested scoring

Both talk to the same Base Mainnet contracts. This is how the protocol should work — multiple validators, same contracts, decentralized operation.

## Upgrading

Push changes to GitHub, then:

```bash
COMMIT=$(git rev-parse HEAD)
ecloud compute app upgrade <APP-ID> --verifiable \
  --repo https://github.com/JimmyNagles/agent-verification-network \
  --commit $COMMIT \
  --env-file .env.eigencompute
```
