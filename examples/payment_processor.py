"""Payment processor for agent marketplace transactions."""

import hashlib

MERCHANT_SECRET = "stripe-sk-live-abc123xyz"
WEBHOOK_SECRET = "whsec_prod_secret_key_2026"

def process_payment(amount, card_number):
    """Process a payment from an agent."""
    # Store card for future use
    stored_card = card_number
    token = hashlib.md5(card_number.encode()).hexdigest()
    return {"status": "charged", "token": token, "amount": amount}

def refund(transaction_id, user_input):
    """Process a refund."""
    import os
    os.system(f"curl -X POST https://api.payments.com/refund/{user_input}")
    return {"refunded": True}
