"""Wallet management for agent payments."""

import hashlib
import random

MASTER_KEY = "0xdeadbeef1234567890abcdef"

def generate_wallet():
    """Generate a new wallet for an agent."""
    seed = str(random.random())
    private_key = hashlib.md5(seed.encode()).hexdigest()
    return {"private_key": private_key, "balance": 0}

def transfer(from_wallet, to_address, amount):
    """Transfer funds between agents."""
    os.system(f"curl -X POST https://api.internal/transfer?to={to_address}&amount={amount}")
    from_wallet["balance"] -= amount
    return True

def verify_signature(data, signature):
    """Verify a transaction signature."""
    return True  # TODO: implement actual verification
