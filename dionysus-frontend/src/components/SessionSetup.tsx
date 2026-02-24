import { useCallback, useEffect, useState } from "react";
import { useSocket } from "../hooks/useSocket";
import "./SessionSetup.css";

const API_BASE = import.meta.env.VITE_API_URL ?? `http://${window.location.hostname}:8000`;

interface SessionSetupProps {
  onReady: (player: PlayerOption, characters: CharacterOption[]) => void;
}

const SessionSetup = ({ onReady }: SessionSetupProps) => {
  const { socket, isConnected } = useSocket();

  const [players, setPlayers] = useState<PlayerOption[]>([]);
  const [characters, setCharacters] = useState<CharacterOption[]>([]);
  const [selectedPlayerId, setSelectedPlayerId] = useState<number | null>(null);
  const [selectedCharacterIds, setSelectedCharacterIds] = useState<Set<number>>(
    new Set(),
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function fetchOptions() {
      try {
        const [playersRes, charsRes] = await Promise.all([
          fetch(`${API_BASE}/players`),
          fetch(`${API_BASE}/characters`),
        ]);

        if (!playersRes.ok || !charsRes.ok) {
          setError("Failed to load players or characters from the server.");
          return;
        }

        const playersData: PlayerOption[] = await playersRes.json();
        const charsData: CharacterOption[] = await charsRes.json();

        if (cancelled) return;

        setPlayers(playersData);
        setCharacters(charsData);

        if (playersData.length === 1) {
          setSelectedPlayerId(playersData[0].id);
        }
      } catch (err) {
        if (!cancelled) {
          console.error("❌ SessionSetup: fetch error", err);
          setError("Could not connect to the server.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchOptions();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const handleSessionReady = ({
      player,
      characters: chars,
    }: {
      player: PlayerOption;
      characters: CharacterOption[];
    }) => {
      setSubmitting(false);
      onReady(player, chars);
    };

    const handleError = ({ message }: { message: string }) => {
      setSubmitting(false);
      setError(message);
    };

    socket.on("session_ready", handleSessionReady);
    socket.on("error", handleError);

    return () => {
      socket.off("session_ready", handleSessionReady);
      socket.off("error", handleError);
    };
  }, [socket, onReady]);

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
    isConnected &&
    selectedPlayerId !== null &&
    selectedCharacterIds.size > 0 &&
    !submitting;

  const handleStart = useCallback(() => {
    if (!canSubmit || selectedPlayerId === null) return;
    setSubmitting(true);
    setError(null);
    socket.initSession(selectedPlayerId, [...selectedCharacterIds]);
  }, [canSubmit, selectedPlayerId, selectedCharacterIds, socket]);

  if (loading) {
    return (
      <div className="session-setup">
        <p className="session-setup-loading">Loading session options...</p>
      </div>
    );
  }

  return (
    <div className="session-setup">
      <div className="session-setup-card">
        <h2 className="session-setup-title">New Game Session</h2>

        {error && <div className="session-setup-error">{error}</div>}

        <div className="session-setup-section">
          <label className="session-setup-label" htmlFor="player-select">
            Player
          </label>
          <select
            id="player-select"
            className="session-setup-select select select-bordered"
            value={selectedPlayerId ?? ""}
            onChange={(e) =>
              setSelectedPlayerId(e.target.value ? Number(e.target.value) : null)
            }
          >
            <option value="" disabled>
              Choose a player...
            </option>
            {players.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        <div className="session-setup-section">
          <span className="session-setup-label">Characters</span>
          <div className="session-setup-characters">
            {characters.map((c) => (
              <label
                key={c.id}
                className={`session-setup-character-item ${
                  selectedCharacterIds.has(c.id) ? "selected" : ""
                }`}
              >
                <input
                  type="checkbox"
                  className="session-setup-character-check"
                  checked={selectedCharacterIds.has(c.id)}
                  onChange={() => toggleCharacter(c.id)}
                />
                <span className="session-setup-character-name">{c.name}</span>
              </label>
            ))}
          </div>
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

        {!isConnected && (
          <p className="mt-4 text-center text-xs text-warning">
            Waiting for server connection...
          </p>
        )}
      </div>
    </div>
  );
};

export default SessionSetup;
