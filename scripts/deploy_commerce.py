#!/usr/bin/env python3
"""
Deploy AgenticCommerce.sol to Base Sepolia or Base Mainnet using Foundry + web3.py.

Usage:
    export PRIVATE_KEY=0xYourPrivateKey
    python3 scripts/deploy_commerce.py              # Base Sepolia (default)
    python3 scripts/deploy_commerce.py mainnet      # Base Mainnet
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
        "rpc": "https://mainnet.base.org",
        "chain_id": 8453,
        "explorer": "https://basescan.org",
        "name": "base-mainnet",
    },
}

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))


def compile_contract():
    """Compile AgenticCommerce.sol using forge."""
    print("Compiling AgenticCommerce.sol...")
    result = subprocess.run(
        ["forge", "build", "--contracts", "contracts", "--out", "contracts/out"],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    if result.returncode != 0:
        print(f"Compilation failed:\n{result.stderr}")
        sys.exit(1)

    artifact_path = os.path.join(
        PROJECT_ROOT, "contracts", "out", "AgenticCommerce.sol", "AgenticCommerce.json"
    )
    with open(artifact_path) as f:
        artifact = json.load(f)

    return artifact["abi"], artifact["bytecode"]["object"]


def deploy(abi, bytecode, network):
    """Deploy contract to the chosen Base network."""
    private_key = os.environ.get("PRIVATE_KEY")
    if not private_key:
        print("ERROR: Set PRIVATE_KEY environment variable")
        print("  export PRIVATE_KEY=0xYourPrivateKey")
        sys.exit(1)

    net = NETWORKS[network]
    w3 = Web3(Web3.HTTPProvider(net["rpc"]))
    if not w3.is_connected():
        print(f"ERROR: Cannot connect to {net['name']} RPC")
        sys.exit(1)

    account = w3.eth.account.from_key(private_key)
    print(f"Deploying to {net['name']} from: {account.address}")
    print(f"Balance: {w3.from_wei(w3.eth.get_balance(account.address), 'ether')} ETH")

    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = contract.constructor().build_transaction({
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
    print(f"AgenticCommerce deployed at: {contract_address}")
    print(f"View: {net['explorer']}/address/{contract_address}")

    deploy_info = {
        "address": contract_address,
        "chain": net["name"],
        "rpc": net["rpc"],
        "tx_hash": tx_hash.hex(),
        "block_number": receipt.blockNumber,
        "abi": abi,
    }
    info_path = os.path.join(PROJECT_ROOT, "contracts", "commerce_deployed.json")
    with open(info_path, "w") as f:
        json.dump(deploy_info, f, indent=2)
    print(f"Saved deployment info to contracts/commerce_deployed.json")

    return contract_address


if __name__ == "__main__":
    network = "sepolia"
    if len(sys.argv) > 1 and sys.argv[1] in NETWORKS:
        network = sys.argv[1]
    elif len(sys.argv) > 1:
        print(f"Unknown network: {sys.argv[1]}. Use 'sepolia' or 'mainnet'.")
        sys.exit(1)

    abi, bytecode = compile_contract()
    deploy(abi, bytecode, network)
