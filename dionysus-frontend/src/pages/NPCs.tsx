import { useMemo } from "react";
import { useNavigate } from "react-router";
import EntityManager from "../components/EntityManager";
import { restService } from "../services/restService";
import "./NPCs.css";

const NPCs = () => {
  const navigate = useNavigate();

  const api = useMemo(
    () => ({
      list: restService.getNpcList,
      get: restService.getNpc,
      create: restService.createNpc,
      updateName: restService.updateNpcName,
      addDescription: restService.addNpcDescription,
      remove: restService.deleteNpc,
    }),
    [],
  );

  const aiButton = (
    <button
      type="button"
      className="btn btn-sm btn-outline btn-primary"
      onClick={() => navigate("/npc-builder")}
    >
      + New NPC (AI Assisted)
    </button>
  );

  return (
    <EntityManager
      title="NPCs"
      entityLabel="NPC"
      api={api}
      extraActions={aiButton}
    />
  );
};

export default NPCs;
