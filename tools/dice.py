from logging import getLogger
import random

from langchain.tools import tool
from pydantic import BaseModel, Field

logger = getLogger(__name__)

ADVANTAGE_STATES = ("advantage", "normal", "disadvantage")


class CheckResult(BaseModel):
    """🎲 Auditable result of a single d20 check against a DC."""
    rolls: list[int] = Field(description="Raw d20 rolls (two when advantage/disadvantage).")
    kept: int = Field(description="The die that counted after advantage/disadvantage.")
    modifier: int = Field(default=0, description="Flat modifier added to the kept die.")
    total: int = Field(description="kept + modifier.")
    dc: int = Field(description="Difficulty class the check was made against.")
    advantage: str = Field(default="normal", description="advantage | normal | disadvantage.")
    outcome: str = Field(description="critical_success | success | failure | critical_failure.")

    def render(self) -> str:
        """Prompt-ready one-line audit of the roll."""
        rolls = "/".join(str(r) for r in self.rolls)
        mod = f" {self.modifier:+d}" if self.modifier else ""
        adv = f", {self.advantage}" if self.advantage != "normal" else ""
        return f"d20[{rolls}] kept {self.kept}{mod} = {self.total} vs DC {self.dc}{adv} -> {self.outcome}"


def resolve_check(dc: int, advantage: str = "normal", modifier: int = 0) -> CheckResult:
    """🎲 Deterministically resolve a d20 check. The LLM never rolls -- this does.

    Natural 20 on the kept die is a critical success, natural 1 a critical
    failure; otherwise the modified total is compared against the DC.
    """
    if advantage not in ADVANTAGE_STATES:
        logger.warning(f"⚠️ Unknown advantage state '{advantage}', treating as normal")
        advantage = "normal"

    rolls = [random.randint(1, 20)]
    if advantage != "normal":
        rolls.append(random.randint(1, 20))
    kept = max(rolls) if advantage == "advantage" else min(rolls)

    total = kept + modifier
    if kept == 20:
        outcome = "critical_success"
    elif kept == 1:
        outcome = "critical_failure"
    elif total >= dc:
        outcome = "success"
    else:
        outcome = "failure"

    result = CheckResult(
        rolls=rolls, kept=kept, modifier=modifier, total=total,
        dc=dc, advantage=advantage, outcome=outcome,
    )
    logger.info(f"🎲 {result.render()}")
    return result


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
