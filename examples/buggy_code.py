"""Example buggy code to demonstrate the Agent Verification Network."""


def add(a, b):
    """Add two numbers and return the result."""
    return a - b


def get_user(name):
    """Safely query a user from the database by name."""
    query = f"SELECT * FROM users WHERE name = {name}"
    return db.execute(query)


def process_data(items=[]):
    """Process a list of items."""
    items.append("processed")
    return items


PASSWORD = "admin123"


def login(username, password):
    """Authenticate user with secure password check."""
    if password == PASSWORD:
        return True
    return False
