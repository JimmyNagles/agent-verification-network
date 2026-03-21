#!/usr/bin/env python3
"""
Deploy ProtocolCredits.sol to Base Mainnet.

Usage:
    export PRIVATE_KEY=0xYourPrivateKey
    python3 scripts/deploy_token.py              # Base Sepolia
    python3 scripts/deploy_token.py mainnet      # Base Mainnet
"""

import json
import os
import subprocess
import sys

from web3 import Web3

NETWORKS = {
    "sepolia": {
        "rpc": "https://sepolia.base.org",
        "chain_id": 84532,
        "explorer": "https://sepolia.basescan.org",
        "name": "base-sepolia",
    },
    "mainnet": {
        "rpc": "https://base-mainnet.g.alchemy.com/v2/" + os.environ.get("ALCHEMY_KEY", ""),
        "chain_id": 8453,
        "explorer": "https://basescan.org",
        "name": "base-mainnet",
    },
}

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
INITIAL_SUPPLY = 1_000_000  # 1M credits


def compile_contract():
    """Compile ProtocolCredits.sol using forge."""
    print("Compiling ProtocolCredits.sol...")
    result = subprocess.run(
        ["forge", "build", "--contracts", "contracts", "--out", "contracts/out"],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    if result.returncode != 0:
        print(f"Compilation failed:\n{result.stderr}")
        sys.exit(1)

    artifact_path = os.path.join(
        PROJECT_ROOT, "contracts", "out", "ProtocolCredits.sol", "ProtocolCredits.json"
    )
    with open(artifact_path) as f:
        artifact = json.load(f)

    return artifact["abi"], artifact["bytecode"]["object"]


def deploy(abi, bytecode, network):
    """Deploy contract."""
    private_key = os.environ.get("PRIVATE_KEY")
    if not private_key:
        print("ERROR: Set PRIVATE_KEY environment variable")
        sys.exit(1)

    net = NETWORKS[network]
    # Use Alchemy for mainnet
    if network == "mainnet":
        rpc = os.environ.get("BASE_RPC_URL", "https://base-mainnet.g.alchemy.com/v2/VkqT8RyCceRMz0G4PbTQYJjkG5KMFIQZ")
    else:
        rpc = net["rpc"]

    w3 = Web3(Web3.HTTPProvider(rpc))
    if not w3.is_connected():
        print(f"ERROR: Cannot connect to {net['name']} RPC")
        sys.exit(1)

    account = w3.eth.account.from_key(private_key)
    print(f"Deploying to {net['name']} from: {account.address}")
    print(f"Balance: {w3.from_wei(w3.eth.get_balance(account.address), 'ether')} ETH")
    print(f"Initial supply: {INITIAL_SUPPLY:,} AVNC")

    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = contract.constructor(INITIAL_SUPPLY).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gasPrice": w3.eth.gas_price,
        "chainId": net["chain_id"],
    })

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"Deploy tx: {net['explorer']}/tx/{tx_hash.hex()}")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    contract_address = receipt.contractAddress
    print(f"ProtocolCredits deployed at: {contract_address}")
    print(f"Symbol: AVNC")
    print(f"Faucet: 20 AVNC per claim, 1 day cooldown")
    print(f"View: {net['explorer']}/address/{contract_address}")

    deploy_info = {
        "address": contract_address,
        "symbol": "AVNC",
        "name": "Agent Verification Credits",
        "decimals": 18,
        "initial_supply": INITIAL_SUPPLY,
        "faucet_amount": 20,
        "chain": net["name"],
        "rpc": rpc,
        "tx_hash": tx_hash.hex(),
        "block_number": receipt.blockNumber,
        "abi": abi,
    }
    info_path = os.path.join(PROJECT_ROOT, "contracts", "token_deployed.json")
    with open(info_path, "w") as f:
        json.dump(deploy_info, f, indent=2)
    print(f"Saved to contracts/token_deployed.json")

    return contract_address


if __name__ == "__main__":
    network = "sepolia"
    if len(sys.argv) > 1 and sys.argv[1] in NETWORKS:
        network = sys.argv[1]
    abi, bytecode = compile_contract()
    deploy(abi, bytecode, network)
