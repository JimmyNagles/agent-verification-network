"""
Spot Check Generator — Creates synthetic buggy code for testing workers.

Managers use this to generate code with KNOWN bugs, then test whether
workers correctly identify them. This is the ground truth for scoring.
"""

import random
from typing import Tuple, List, Dict


class SpotCheckGenerator:
    """Generate code snippets with known injected bugs for worker testing."""

    def __init__(self):
        self.templates = self._build_templates()

    def generate(self) -> Tuple[str, str, List[Dict]]:
        """
        Generate a spot check: buggy code + intent + known bugs.

        Returns:
            (buggy_code, intent, known_bugs)
            known_bugs: list of {type, severity, line, description}
        """
        template = random.choice(self.templates)
        variant = random.choice(template["variants"])

        return variant["code"], template["intent"], variant["bugs"]

    def _build_templates(self) -> list:
        """Build the bank of spot check templates."""
        return [
            # ── Template 1: Off-by-one error ──────────────────────
            {
                "intent": "Calculate the sum of numbers from 1 to n (inclusive)",
                "variants": [
                    {
                        "code": "def sum_to_n(n):\n    total = 0\n    for i in range(n):\n        total += i\n    return total",
                        "bugs": [
                            {
                                "type": "off_by_one",
                                "severity": "high",
                                "line": 3,
                                "description": "range(n) goes 0 to n-1, should be range(1, n+1) for 1 to n inclusive",
                            }
                        ],
                    },
                    {
                        "code": "def sum_to_n(n):\n    return sum(range(n))",
                        "bugs": [
                            {
                                "type": "off_by_one",
                                "severity": "high",
                                "line": 2,
                                "description": "range(n) gives 0 to n-1, should be range(1, n+1) for 1 to n inclusive",
                            }
                        ],
                    },
                ],
            },

            # ── Template 2: Wrong operator ────────────────────────
            {
                "intent": "Add two numbers together and return the result",
                "variants": [
                    {
                        "code": "def add(a, b):\n    return a - b",
                        "bugs": [
                            {
                                "type": "logic_error",
                                "severity": "critical",
                                "line": 2,
                                "description": "Uses subtraction (-) instead of addition (+)",
                            }
                        ],
                    },
                    {
                        "code": "def add(a, b):\n    result = a * b\n    return result",
                        "bugs": [
                            {
                                "type": "logic_error",
                                "severity": "critical",
                                "line": 2,
                                "description": "Uses multiplication (*) instead of addition (+)",
                            }
                        ],
                    },
                ],
            },

            # ── Template 3: Missing edge case ─────────────────────
            {
                "intent": "Find the maximum value in a list. Handle empty lists.",
                "variants": [
                    {
                        "code": "def find_max(lst):\n    max_val = lst[0]\n    for item in lst[1:]:\n        if item > max_val:\n            max_val = item\n    return max_val",
                        "bugs": [
                            {
                                "type": "missing_edge_case",
                                "severity": "high",
                                "line": 2,
                                "description": "No check for empty list — will raise IndexError on lst[0]",
                            }
                        ],
                    },
                ],
            },

            # ── Template 4: Security — SQL injection ──────────────
            {
                "intent": "Look up a user by username from the database safely",
                "variants": [
                    {
                        "code": 'def get_user(db, username):\n    query = f"SELECT * FROM users WHERE name = \'{username}\'"\n    return db.execute(query)',
                        "bugs": [
                            {
                                "type": "security",
                                "severity": "critical",
                                "line": 2,
                                "description": "SQL injection vulnerability — user input directly interpolated into query string",
                            }
                        ],
                    },
                ],
            },

            # ── Template 5: Mutable default argument ──────────────
            {
                "intent": "Append an item to a list and return it. Create a new list if none provided.",
                "variants": [
                    {
                        "code": "def append_item(item, lst=[]):\n    lst.append(item)\n    return lst",
                        "bugs": [
                            {
                                "type": "bug",
                                "severity": "high",
                                "line": 1,
                                "description": "Mutable default argument — the list is shared across all calls, causing unexpected accumulation",
                            }
                        ],
                    },
                ],
            },

            # ── Template 6: Logic inversion ───────────────────────
            {
                "intent": "Check if a number is positive and return True if it is",
                "variants": [
                    {
                        "code": "def is_positive(n):\n    return n < 0",
                        "bugs": [
                            {
                                "type": "logic_error",
                                "severity": "critical",
                                "line": 2,
                                "description": "Logic inverted — returns True when n is negative instead of positive. Should be n > 0",
                            }
                        ],
                    },
                    {
                        "code": "def is_positive(n):\n    if n <= 0:\n        return True\n    return False",
                        "bugs": [
                            {
                                "type": "logic_error",
                                "severity": "critical",
                                "line": 2,
                                "description": "Logic inverted — returns True when n is non-positive instead of positive",
                            }
                        ],
                    },
                ],
            },

            # ── Template 7: Type error ────────────────────────────
            {
                "intent": "Concatenate a greeting with a user's name",
                "variants": [
                    {
                        "code": 'def greet(name, age):\n    return "Hello " + name + ", you are " + age + " years old"',
                        "bugs": [
                            {
                                "type": "type_error",
                                "severity": "high",
                                "line": 2,
                                "description": "TypeError — concatenating string with integer (age). Need str(age)",
                            }
                        ],
                    },
                ],
            },

            # ── Template 8: Infinite loop risk ────────────────────
            {
                "intent": "Count down from n to 0 and return the count of steps",
                "variants": [
                    {
                        "code": "def countdown(n):\n    steps = 0\n    while n > 0:\n        steps += 1\n    return steps",
                        "bugs": [
                            {
                                "type": "bug",
                                "severity": "critical",
                                "line": 3,
                                "description": "Infinite loop — n is never decremented inside the while loop",
                            }
                        ],
                    },
                ],
            },

            # ── Template 9: Wrong return value ────────────────────
            {
                "intent": "Calculate the average of a list of numbers",
                "variants": [
                    {
                        "code": "def average(numbers):\n    total = sum(numbers)\n    return total",
                        "bugs": [
                            {
                                "type": "logic_error",
                                "severity": "high",
                                "line": 3,
                                "description": "Returns the sum instead of the average — missing division by len(numbers)",
                            }
                        ],
                    },
                    {
                        "code": "def average(numbers):\n    total = sum(numbers)\n    count = len(numbers)\n    return total * count",
                        "bugs": [
                            {
                                "type": "logic_error",
                                "severity": "high",
                                "line": 4,
                                "description": "Multiplies total by count instead of dividing — returns wrong result",
                            }
                        ],
                    },
                ],
            },

            # ── Template 10: Hardcoded credentials ────────────────
            {
                "intent": "Connect to the database using environment configuration",
                "variants": [
                    {
                        "code": 'def connect_db():\n    password = "admin123"\n    return db.connect(host="localhost", password=password)',
                        "bugs": [
                            {
                                "type": "security",
                                "severity": "critical",
                                "line": 2,
                                "description": "Hardcoded password — should use environment variables or secrets manager",
                            }
                        ],
                    },
                ],
            },

            # ── Template 11: Clean code (no bugs) ─────────────────
            # Important: some spot checks should have NO bugs to test false positive rate
            {
                "intent": "Return the factorial of a non-negative integer",
                "variants": [
                    {
                        "code": "def factorial(n):\n    if n < 0:\n        raise ValueError('n must be non-negative')\n    if n == 0:\n        return 1\n    return n * factorial(n - 1)",
                        "bugs": [],  # No bugs — tests false positive rate
                    },
                ],
            },
            {
                "intent": "Reverse a string and return it",
                "variants": [
                    {
                        "code": "def reverse_string(s):\n    return s[::-1]",
                        "bugs": [],  # No bugs
                    },
                ],
            },
        ]


# Backward-compatible alias
HoneypotGenerator = SpotCheckGenerator
