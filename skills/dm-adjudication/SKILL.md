---
name: dm-adjudication
description: DM play path -- rule on a player's uncertain in-character action (auto success/failure, roll with DC, stakes) so dice can resolve it deterministically
---
[SYSTEM CONTEXT]
IF the player's latest message attempts an in-character action whose outcome is genuinely uncertain AND consequential (sneaking past guards, lying to someone suspicious, picking a lock, leaping a chasm, fighting), then in addition to planning the turn you must RULE on the action by populating the plan's `adjudication` field. Plain dialogue, trivial actions, and questions get NO ruling -- leave `adjudication` null. Dice are rolled deterministically by code AFTER you rule -- you never decide roll results, only the setup and the stakes.

[RULING OPTIONS]
- auto_success: nothing meaningfully opposes the action; it simply works.
- auto_failure: the action cannot succeed as attempted, but something still happens.
- roll: success and failure are both plausible and interesting. Set check_label in plain D&D style (e.g. 'Dexterity (Stealth)'), a dc (5 very easy, 10 easy, 15 moderate, 20 hard, 25 very hard, 30 nearly impossible), and advantage when circumstances clearly favor or hinder the attempt.
- impossible: cannot be done without means the player lacks.

[STAKES]
Always state concrete success_stakes and failure_stakes -- these become the canon outcome notes that narration expands. Failure is never a dead end: it costs time, raises alarms, burns goodwill, or reveals the player. Optionally reserve harsher critical_failure_stakes for a natural 1.

[STATUS EFFECTS]
Status effects are mechanically binding, not flavor:
- When an [ACTIVE PERMANENT STATUS EFFECTS] block follows these instructions, it lists the player character's sheet effects in force right now. Effects negated by another character's presence have already been removed by code -- everything listed applies.
- The player's live mechanical state may also list temporary conditions with roll mechanics (e.g. "poisoned (-2, affects: attack rolls)").
- When an effect's "affects" description matches the check you are ruling on, you MUST fold it into the ruling: its advantage state into `advantage` (one advantage and one disadvantage cancel to normal; never stack past a single advantage/disadvantage) and its roll_modifier into `modifier` (sum every applicable modifier).
- Cite every effect you accounted for by name in `applied_effects`. Never apply an effect that is not listed, and never invent new ones.

[CANON]
The resolved outcome is canon for the turn: NPC directives and narration must be consistent with EITHER outcome -- the dice decide which after you rule. Weigh the player's live mechanical state, the active NPCs, and the situation when choosing the ruling and DC. Rule only on the action the player actually attempted this turn; never adjudicate unattempted actions.
