import { useCallback, useMemo } from "react";
import { useNavigate } from "react-router";
import EntityManager from "../components/EntityManager";
import CharacterStatusEffects from "../components/CharacterStatusEffects";
import { restService } from "../services/restService";
import type { EntityDetailResponse } from "../types/rest";
import "./Characters.css";

const Characters = () => {
  const navigate = useNavigate();

  const api = useMemo(
    () => ({
      list: restService.getCharacterList,
      get: restService.getCharacter,
      create: restService.createCharacter,
      updateName: restService.updateCharacterName,
      addDescription: restService.addCharacterDescription,
      remove: restService.deleteCharacter,
    }),
    [],
  );

  const aiButton = (
    <button
      type="button"
      className="btn btn-sm btn-outline btn-primary"
      onClick={() => navigate("/npc-builder")}
    >
      + New Character (AI Assisted)
    </button>
  );

  const renderExtras = useCallback(
    (detail: EntityDetailResponse, refresh: () => Promise<void>) => (
      <CharacterStatusEffects
        characterId={detail.id}
        effects={detail.status_effects ?? []}
        onChanged={refresh}
      />
    ),
    [],
  );

  return (
    <EntityManager
      title="Characters"
      entityLabel="Character"
      api={api}
      extraActions={aiButton}
      renderExtras={renderExtras}
    />
  );
};

export default Characters;
