import { useMemo } from "react";
import EntityManager from "../components/EntityManager";
import { restService } from "../services/restService";
import "./Players.css";

const Players = () => {
  const api = useMemo(
    () => ({
      list: restService.getPlayerList,
      get: restService.getPlayer,
      create: restService.createPlayer,
      updateName: restService.updatePlayerName,
      addDescription: restService.addPlayerDescription,
      remove: restService.deletePlayer,
    }),
    [],
  );

  return <EntityManager title="Players" entityLabel="Player" api={api} />;
};

export default Players;
