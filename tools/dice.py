from logging import getLogger
import random

from langchain.tools import tool

logger = getLogger(__name__)

@tool
def roll_d20() -> int:
    """Roll a 20-sided die."""
    return random.randint(1, 20)

@tool
def roll_d10() -> int:
    """Roll a 10-sided die."""
    return random.randint(1, 10)

@tool
def roll_d6() -> int:
    """Roll a 6-sided die."""
    return random.randint(1, 6)