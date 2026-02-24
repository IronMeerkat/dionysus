import { useCallback, useEffect, useState } from "react";
import "./SessionSetup.css";
import { useOptionsStore, useSessionStore } from "../contexts/SessionStore";
import { restService } from "../services/restService";
import { useNavigate } from "react-router";
import PlayerSelect from "../components/PlayerSelect";
import CharacterSelect from "../components/CharacterSelect";


const SessionSetup = () => {
  const navigate = useNavigate();

  const { players, characters, setPlayers, setCharacters } = useOptionsStore();
  const { setPlayer , setCharacters: setSessionCharacters } = useSessionStore();

  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null);
  const [selectedCharacterIds, setSelectedCharacterIds] = useState<Set<number>>(new Set());
  const [startNewConversation, setStartNewConversation] = useState(false);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {

    async function fetchOptions() {
      try {
        const options = await restService.getOptions();

        setPlayers(options.players);
        setCharacters(options.characters);

        if (options.players.length === 1) {
          setSelectedPlayerId(options.players[0].id);
        }
        } catch (err) {
          console.error("❌ SessionSetup: fetch error", err);
          setError("Could not connect to the server.");
        } finally {
        setLoading(false);
      }
    }

    fetchOptions();
  }, []);


  const toggleCharacter = useCallback((id: number) => {
    setSelectedCharacterIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const canSubmit =
    selectedPlayerId !== null &&
    selectedCharacterIds.size > 0 &&
    !submitting;

  const handleStart = useCallback(async () => {
    if (!canSubmit || selectedPlayerId === null) return;
    setSubmitting(true);
    setError(null);
    // ReST call here
    await restService.setupSession(selectedPlayerId, Array.from(selectedCharacterIds), startNewConversation).then(() => {
      // socketService.initSession(selectedPlayerId, Array.from(selectedCharacterIds));
      setPlayer(players.find((p) => p.id === selectedPlayerId)!);
      setSessionCharacters(characters.filter((c) => selectedCharacterIds.has(c.id)));
      navigate("/", { replace: true });
    }).catch((error: Error) => {
      setError(error.message);
    }).finally(() => {
      setSubmitting(false);
    });
  }, [canSubmit, selectedPlayerId, selectedCharacterIds]);

  if (loading) {
    return (
      <div className="chat-layout">
        <div className="session-setup">
          <p className="session-setup-loading">Loading session options...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="session-setup">
      <div className="session-setup-card">
        <h2 className="session-setup-title">New Game Session</h2>

        {error && <div className="session-setup-error">{error}</div>}

        <PlayerSelect
          items={players}
          selectedId={selectedPlayerId}
          onChange={setSelectedPlayerId}
        />

        <CharacterSelect
          items={characters}
          selectedIds={selectedCharacterIds}
          onToggle={toggleCharacter}
        />

        <div className="session-setup-section">
          <label
              key="start-new-conversation"
              className={`session-setup-character-item ${
                startNewConversation ? "selected" : ""
              }`}
            >
              <input
                type="checkbox"
                className="session-setup-character-check"
                checked={startNewConversation}
                onChange={() => setStartNewConversation(!startNewConversation)}
              />
              <span className="session-setup-character-name">Start new conversation</span>
            </label>

        </div>
        <div className="session-setup-footer">

          <button
            type="button"
            className="session-setup-submit btn btn-primary"
            disabled={!canSubmit}
            onClick={handleStart}
          >
            {submitting ? "Starting..." : "Start Session"}
          </button>
          
        </div>

      </div>
    </div>
  );
};

export default SessionSetup;
