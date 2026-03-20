#!/usr/bin/env python3
"""
Deploy AgentScorer.sol to Base Sepolia using Foundry + web3.py.

Usage:
    export PRIVATE_KEY=0xYourPrivateKey
    python3 scripts/deploy_contract.py

The contract address is printed and saved to contracts/deployed_address.txt.
"""

import json
import os
import subprocess
import sys

from web3 import Web3

BASE_SEPOLIA_RPC = "https://sepolia.base.org"
CHAIN_ID = 84532

def compile_contract():
    """Compile AgentScorer.sol using forge."""
    print("Compiling AgentScorer.sol...")
    result = subprocess.run(
        ["forge", "build", "--contracts", "contracts", "--out", "contracts/out"],
        capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__))
    )
    if result.returncode != 0:
        print(f"Compilation failed:\n{result.stderr}")
        sys.exit(1)

    # Read compiled artifact
    artifact_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "contracts", "out", "AgentScorer.sol", "AgentScorer.json"
    )
    with open(artifact_path) as f:
        artifact = json.load(f)

    return artifact["abi"], artifact["bytecode"]["object"]


def deploy(abi, bytecode):
    """Deploy contract to Base Sepolia."""
    private_key = os.environ.get("PRIVATE_KEY")
    if not private_key:
        print("ERROR: Set PRIVATE_KEY environment variable")
        print("  export PRIVATE_KEY=0xYourPrivateKey")
        sys.exit(1)

    w3 = Web3(Web3.HTTPProvider(BASE_SEPOLIA_RPC))
    if not w3.is_connected():
        print("ERROR: Cannot connect to Base Sepolia RPC")
        sys.exit(1)

    account = w3.eth.account.from_key(private_key)
    print(f"Deploying from: {account.address}")
    print(f"Balance: {w3.from_wei(w3.eth.get_balance(account.address), 'ether')} ETH")

    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = contract.constructor().build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gasPrice": w3.eth.gas_price,
        "chainId": CHAIN_ID,
    })

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"Deploy tx: https://sepolia.basescan.org/tx/{tx_hash.hex()}")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    contract_address = receipt.contractAddress
    print(f"Contract deployed at: {contract_address}")
    print(f"View: https://sepolia.basescan.org/address/{contract_address}")

    # Save address and ABI for the validator
    deploy_info = {
        "address": contract_address,
        "chain": "base-sepolia",
        "rpc": BASE_SEPOLIA_RPC,
        "tx_hash": tx_hash.hex(),
        "block_number": receipt.blockNumber,
        "abi": abi,
    }
    info_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "contracts", "deployed.json")
    with open(info_path, "w") as f:
        json.dump(deploy_info, f, indent=2)
    print(f"Saved deployment info to contracts/deployed.json")

    return contract_address


if __name__ == "__main__":
    abi, bytecode = compile_contract()
    deploy(abi, bytecode)
