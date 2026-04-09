import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router";
import "./CharacterMemories.css";
import { restService } from "../services/restService";
import type { VectorMemoryApi } from "../types/rest";
import VectorMemoryWorld from "../components/VectorMemoryWorld";

const CharacterMemories = () => {
  const { campaignId, npcId } = useParams<{
    campaignId: string;
    npcId: string;
  }>();
  const navigate = useNavigate();

  const cid = Number(campaignId);
  const nid = Number(npcId);

  const [npcName, setNpcName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!campaignId || !npcId) return;
    restService
      .getCampaign(cid)
      .then((campaign) => {
        const npc = campaign.npcs.find((n) => n.id === nid);
        if (npc) {
          setNpcName(npc.name);
        } else {
          setError("NPC not found in this campaign.");
        }
      })
      .catch((err) => {
        console.error("❌ Failed to load campaign:", err);
        setError("Could not load campaign.");
      })
      .finally(() => setLoading(false));
  }, [campaignId, npcId, cid, nid]);

  const memoryApi: VectorMemoryApi = useMemo(
    () => ({
      getEntries: () =>
        restService.getCharacterMemoryEntries(cid, nid),
      getEntry: (uuid: string) =>
        restService.getCharacterMemoryEntry(uuid),
      createEntry: (title: string, content: string) =>
        restService.createCharacterMemoryEntry(cid, nid, title, content),
      updateEntry: (uuid: string, title: string, content: string) =>
        restService.updateCharacterMemoryEntry(uuid, title, content),
      deleteEntry: (uuid: string) =>
        restService.deleteCharacterMemoryEntry(uuid),
    }),
    [cid, nid],
  );

  if (loading) {
    return (
      <div className="char-memories-page">
        <p className="char-memories-loading">Loading...</p>
      </div>
    );
  }

  if (error || !npcName) {
    return (
      <div className="char-memories-page">
        <div className="char-memories-container">
          <div className="char-memories-error">
            {error ?? "Something went wrong."}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="char-memories-page">
      <div className="char-memories-container">
        <div className="char-memories-header">
          <button
            type="button"
            className="char-memories-back"
            onClick={() => navigate(`/campaigns/${cid}`)}
          >
            &larr; Back
          </button>
          <h2 className="char-memories-title">{npcName} &mdash; Memories</h2>
        </div>

        <VectorMemoryWorld api={memoryApi} />
      </div>
    </div>
  );
};

export default CharacterMemories;
