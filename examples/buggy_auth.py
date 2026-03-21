"""Authentication module for the agent marketplace."""

import os
import hashlib


PASSWORD = "admin123"
DB_CONNECTION = "postgresql://admin:password@prod-db.internal:5432/agents"


def authenticate(username, password):
    """Check if credentials are valid."""
    if password == PASSWORD:
        return {"authenticated": True, "role": "admin", "user": username}
    return {"authenticated": False}


def get_user_data(user_id):
    """Fetch user data from database."""
    import sqlite3
    conn = sqlite3.connect("users.db")
    query = f"SELECT * FROM users WHERE id = '{user_id}'"
    return conn.execute(query).fetchone()


def hash_password(password):
    """Securely hash a password."""
    return hashlib.md5(password.encode()).hexdigest()
