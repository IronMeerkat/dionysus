import logging

from fastapi import APIRouter, Body
from fastapi.exceptions import HTTPException
from sqlalchemy.orm import Session

from database.models.character import Character, CharacterStatusEffect
from database.postgres_connection import db_session
from database.session_utils import embedder
from tools.dice import ADVANTAGE_STATES

logger = logging.getLogger(__name__)

characters_router = APIRouter(prefix="/characters")


def _refresh_character_embedding(character: Character) -> None:
    """🧬 Best-effort re-embed of name+description for semantic dedup.

    Fail-secure: an embedder hiccup must never fail a character write --
    log and leave the previous/NULL vector in place.
    """
    try:
        character.embedding = embedder.embed_query(
            Character.embedding_text(character.name, character.description or "")
        )
    except Exception:
        logger.exception(f"💥 Embedding failed for character '{character.name}'; keeping old vector")


def _character_list_item(character: Character) -> dict[str, object]:
    return {
        "id": character.id,
        "name": character.name,
        "description": character.description,
        "description_version": character.description_version,
        "created_at": character.created_at.isoformat(),
    }


def _status_effect_dict(effect: CharacterStatusEffect) -> dict[str, object]:
    return {
        "id": effect.id,
        "character_id": effect.character_id,
        "name": effect.name,
        "description": effect.description,
        "affects": effect.affects,
        "roll_modifier": effect.roll_modifier,
        "advantage": effect.advantage,
        "negated_by": effect.negated_by or [],
        "negation_condition": effect.negation_condition,
        "created_at": effect.created_at.isoformat(),
        "updated_at": effect.updated_at.isoformat(),
    }


def _character_full(character: Character) -> dict[str, object]:
    return {
        "id": character.id,
        "name": character.name,
        "created_at": character.created_at.isoformat(),
        "descriptions": [
            {
                "version": desc.version,
                "body": desc.body,
                "created_at": desc.created_at.isoformat(),
            }
            for desc in character.description_versions
        ],
        "status_effects": [_status_effect_dict(e) for e in character.status_effects],
    }


def _get_character(s: Session, character_id: int) -> Character:
    character = s.query(Character).filter(Character.id == character_id).first()
    if not character:
        raise HTTPException(status_code=404, detail=f"Character {character_id} not found")
    return character


@characters_router.get("/")
def list_characters() -> list[dict[str, object]]:
    with db_session() as s:
        characters = s.query(Character).order_by(Character.name.asc()).all()
        return [_character_list_item(c) for c in characters]


@characters_router.get("/{character_id}")
def get_character(character_id: int) -> dict[str, object]:
    with db_session() as s:
        character = _get_character(s, character_id)
        return _character_full(character)


@characters_router.post("/", status_code=201)
def create_character(
    name: str = Body(..., embed=True),
    description: str = Body("", embed=True),
) -> dict[str, object]:
    with db_session() as s:
        existing = s.query(Character).filter(Character.name == name).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Character '{name}' already exists")
        character = Character(name=name)
        if description.strip():
            character.add_description(description.strip())
        s.add(character)
        _refresh_character_embedding(character)
        s.flush()
        response = _character_full(character)
        logger.info(f"🎭 Created character '{name}' (id={character.id})")
        return response


@characters_router.put("/{character_id}")
def update_character(
    character_id: int,
    name: str = Body(..., embed=True),
) -> dict[str, object]:
    with db_session() as s:
        character = _get_character(s, character_id)
        dup = s.query(Character).filter(Character.name == name, Character.id != character_id).first()
        if dup:
            raise HTTPException(status_code=409, detail=f"Character '{name}' already exists")
        character.name = name
        _refresh_character_embedding(character)
        s.flush()
        logger.info(f"✏️ Updated character {character_id} name to '{name}'")
        return _character_full(character)


@characters_router.post("/{character_id}/description", status_code=201)
def add_character_description(
    character_id: int,
    body: str = Body(..., embed=True),
) -> dict[str, object]:
    with db_session() as s:
        character = _get_character(s, character_id)
        character.add_description(body.strip())
        _refresh_character_embedding(character)
        s.flush()
        logger.info(f"📝 Added description v{character.description_version} to character '{character.name}'")
        return _character_full(character)


@characters_router.delete("/{character_id}")
def delete_character(character_id: int) -> dict[str, str]:
    with db_session() as s:
        character = _get_character(s, character_id)
        name = character.name
        s.delete(character)
    logger.info(f"🗑️ Deleted character '{name}' (id={character_id})")
    return {"detail": f"Character '{name}' deleted"}


# ------------------------------------------------------------------
# Permanent status effects
# ------------------------------------------------------------------


def _get_status_effect(character: Character, effect_id: int) -> CharacterStatusEffect:
    effect = next((e for e in character.status_effects if e.id == effect_id), None)
    if effect is None:
        raise HTTPException(
            status_code=404,
            detail=f"Status effect {effect_id} not found on character '{character.name}'",
        )
    return effect


def _validate_advantage(advantage: str) -> str:
    if advantage not in ADVANTAGE_STATES:
        raise HTTPException(
            status_code=422,
            detail=f"advantage must be one of: {', '.join(ADVANTAGE_STATES)}",
        )
    return advantage


@characters_router.post("/{character_id}/status_effects", status_code=201)
def create_status_effect(
    character_id: int,
    name: str = Body(...),
    description: str = Body(""),
    affects: str = Body(""),
    roll_modifier: int = Body(0),
    advantage: str = Body("normal"),
    negated_by: list[str] = Body([]),
    negation_condition: str | None = Body(None),
) -> dict[str, object]:
    with db_session() as s:
        character = _get_character(s, character_id)
        _validate_advantage(advantage)
        if any(e.name.lower() == name.strip().lower() for e in character.status_effects):
            raise HTTPException(
                status_code=409,
                detail=f"Character '{character.name}' already has a status effect named '{name.strip()}'",
            )
        effect = CharacterStatusEffect(
            character_id=character.id,
            name=name.strip(),
            description=description.strip(),
            affects=affects.strip(),
            roll_modifier=roll_modifier,
            advantage=advantage,
            negated_by=[n.strip() for n in negated_by if n.strip()],
            negation_condition=negation_condition.strip() if negation_condition else None,
        )
        character.status_effects.append(effect)
        s.flush()
        logger.info(f"🧬 Created status effect '{effect.name}' for character '{character.name}'")
        return _status_effect_dict(effect)


@characters_router.put("/{character_id}/status_effects/{effect_id}")
def update_status_effect(
    character_id: int,
    effect_id: int,
    name: str = Body(...),
    description: str = Body(""),
    affects: str = Body(""),
    roll_modifier: int = Body(0),
    advantage: str = Body("normal"),
    negated_by: list[str] = Body([]),
    negation_condition: str | None = Body(None),
) -> dict[str, object]:
    with db_session() as s:
        character = _get_character(s, character_id)
        effect = _get_status_effect(character, effect_id)
        _validate_advantage(advantage)
        if any(
            e.id != effect_id and e.name.lower() == name.strip().lower()
            for e in character.status_effects
        ):
            raise HTTPException(
                status_code=409,
                detail=f"Character '{character.name}' already has a status effect named '{name.strip()}'",
            )
        effect.name = name.strip()
        effect.description = description.strip()
        effect.affects = affects.strip()
        effect.roll_modifier = roll_modifier
        effect.advantage = advantage
        effect.negated_by = [n.strip() for n in negated_by if n.strip()]
        effect.negation_condition = negation_condition.strip() if negation_condition else None
        s.flush()
        logger.info(f"🧬 Updated status effect '{effect.name}' (id={effect_id}) for '{character.name}'")
        return _status_effect_dict(effect)


@characters_router.delete("/{character_id}/status_effects/{effect_id}")
def delete_status_effect(character_id: int, effect_id: int) -> dict[str, str]:
    with db_session() as s:
        character = _get_character(s, character_id)
        effect = _get_status_effect(character, effect_id)
        name = effect.name
        character_name = character.name
        s.delete(effect)
    logger.info(f"🗑️ Deleted status effect '{name}' (id={effect_id}) from '{character_name}'")
    return {"detail": f"Status effect '{name}' deleted"}
