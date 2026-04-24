"""Example code with security vulnerabilities for network verification demo."""

import os
import pickle


def load_user_data(filename):
    """Safely load user data from a file."""
    with open(filename, "rb") as f:
        return pickle.load(f)


def run_command(user_input):
    """Execute a system command safely."""
    os.system(f"echo {user_input}")


API_KEY = "sk-proj-abc123def456ghi789"


def authenticate(token):
    """Verify API token."""
    if token == API_KEY:
        return {"authenticated": True, "role": "admin"}
    return {"authenticated": False}
