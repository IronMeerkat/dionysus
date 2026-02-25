import { useCallback, useEffect, useState } from "react";
import "./SessionSetup.css";
import { useOptionsStore, useSessionStore } from "../contexts/SessionStore";
import { useConversationStore } from "../contexts/ConversationStore";
import { useMessageStore } from "../contexts/MessageStore";
import { restService } from "../services/restService";
import { useNavigate } from "react-router";
import PlayerSelect from "../components/PlayerSelect";
import CharacterSelect from "../components/CharacterSelect";
import ChatSidebar from "../components/ChatSidebar";

interface SessionSetupProps {
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
}

const SessionSetup = ({ sidebarOpen, onToggleSidebar }: SessionSetupProps) => {
  const navigate = useNavigate();

  const { players, characters, setPlayers, setCharacters } = useOptionsStore();
  const { setPlayer, setCharacters: setSessionCharacters } = useSessionStore();
  const { setActiveConversation } = useConversationStore();
  const setMessages = useMessageStore((s) => s.setMessages);

  const navigateToChat = useCallback(() => {
    navigate("/", { replace: true });
  }, [navigate]);

  const closeSidebar = useCallback(() => {
    if (sidebarOpen) onToggleSidebar();
  }, [sidebarOpen, onToggleSidebar]);

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
    await restService.setupSession(selectedPlayerId, Array.from(selectedCharacterIds), startNewConversation).then(response => {
      // socketService.initSession(selectedPlayerId, Array.from(selectedCharacterIds));
      setPlayer(players.find((p) => p.id === selectedPlayerId)!);
      setSessionCharacters(characters.filter((c) => selectedCharacterIds.has(c.id)));
      setActiveConversation(response.id, response.title);
      setMessages(response.messages.map((m) => ({
        id: m.id,
        content: m.content,
        role: m.role,
        name: m.name,
        createdAt: new Date(m.created_at),
      })));
      navigate("/", { replace: true });
    }).catch((error: Error) => {
      setError(error.message);
    }).finally(() => {
      setSubmitting(false);
    });
  }, [canSubmit, selectedPlayerId, selectedCharacterIds, startNewConversation]);

  if (loading) {
    return (
      <div className="page-layout">
        <ChatSidebar mobileOpen={sidebarOpen} onClose={closeSidebar} onAfterSelect={navigateToChat} />
        <div className="session-setup">
          <p className="session-setup-loading">Loading session options...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="page-layout">
      <ChatSidebar mobileOpen={sidebarOpen} onClose={closeSidebar} onAfterSelect={navigateToChat} />

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
              className="btn-action btn btn-primary"
              disabled={!canSubmit}
              onClick={handleStart}
            >
              {submitting ? "Starting..." : "Start Session"}
            </button>
            
          </div>

        </div>
      </div>
    </div>
  );
};

export default SessionSetup;
