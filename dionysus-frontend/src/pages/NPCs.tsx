import { useMemo } from "react";
import EntityManager from "../components/EntityManager";
import { restService } from "../services/restService";
import "./NPCs.css";

const NPCs = () => {
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

  return <EntityManager title="NPCs" entityLabel="NPC" api={api} />;
};

export default NPCs;
