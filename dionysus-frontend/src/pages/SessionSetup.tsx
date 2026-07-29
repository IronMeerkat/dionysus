import { useCallback, useEffect, useState } from "react";
import "./SessionSetup.css";
import { useOptionsStore, useSessionStore } from "../contexts/SessionStore";
import { useConversationStore } from "../contexts/ConversationStore";
import { useMessageStore } from "../contexts/MessageStore";
import { restService } from "../services/restService";
import { useNavigate, useSearchParams } from "react-router";
import PlayerSelect from "../components/PlayerSelect";
import CharacterSelect from "../components/CharacterSelect";
import ChatSidebar from "../components/ChatSidebar";

interface SessionSetupProps {
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
}

const SessionSetup = ({ sidebarOpen, onToggleSidebar }: SessionSetupProps) => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const campaignId = searchParams.get("campaign_id");

  useEffect(() => {
    if (!campaignId) navigate("/campaigns", { replace: true });
  }, [campaignId, navigate]);

  const { characters, setCharacters } = useOptionsStore();
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

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {

    async function fetchOptions() {
      try {
        const options = await restService.getOptions();

        setCharacters(options.characters);

        if (options.characters.length === 1) {
          setSelectedPlayerId(options.characters[0].id);
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

  console.log("canSubmit", canSubmit);

  const handleStart = useCallback(async () => {
    if (!canSubmit || selectedPlayerId === null || !campaignId) return;
    setSubmitting(true);
    setError(null);
    await restService.setupSession(selectedPlayerId, Array.from(selectedCharacterIds), Number(campaignId)).then(response => {
      setPlayer(characters.find((c) => c.id === selectedPlayerId)!);
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
  }, [canSubmit, selectedPlayerId, selectedCharacterIds, campaignId]);

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
            items={characters}
            selectedId={selectedPlayerId}
            onChange={(id) => {
              setSelectedPlayerId(id);
              // The PC can't also be in the scene as an NPC.
              if (id !== null) {
                setSelectedCharacterIds((prev) => {
                  if (!prev.has(id)) return prev;
                  const next = new Set(prev);
                  next.delete(id);
                  return next;
                });
              }
            }}
          />

          <CharacterSelect
            items={characters.filter((c) => c.id !== selectedPlayerId)}
            selectedIds={selectedCharacterIds}
            onToggle={toggleCharacter}
          />

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
