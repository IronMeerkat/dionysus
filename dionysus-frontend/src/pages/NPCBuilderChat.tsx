import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams, useNavigate } from "react-router";
import { io, Socket } from "socket.io-client";
import type {
  NPCBuilderServerToClientEvents,
  NPCBuilderClientToServerEvents,
  NPCBuilderTokenPayload,
  NPCBuilderCreatedPayload,
  SocketErrorPayload,
} from "../types/socket";
import type { WorldResponse } from "../types/rest";
import { restService } from "../services/restService";
import "./NPCBuilderChat.css";

type BuilderSocket = Socket<NPCBuilderServerToClientEvents, NPCBuilderClientToServerEvents>;

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

const SOCKET_URL =
  import.meta.env.VITE_SOCKET_URL ?? `http://${window.location.hostname}:8000`;

const NPCBuilderChat = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const worldName = searchParams.get("world") ?? "";

  const socketRef = useRef<BuilderSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const [worlds, setWorlds] = useState<WorldResponse[]>([]);
  const [loadingWorlds, setLoadingWorlds] = useState(true);
  const [worldError, setWorldError] = useState<string | null>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [connected, setConnected] = useState(false);
  const [sessionReady, setSessionReady] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [createdName, setCreatedName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (worldName) return;
    setLoadingWorlds(true);
    restService
      .getWorlds()
      .then(setWorlds)
      .catch((err) => {
        console.error("Failed to fetch worlds", err);
        setWorldError("Could not load worlds.");
      })
      .finally(() => setLoadingWorlds(false));
  }, [worldName]);

  useEffect(() => {
    if (!worldName) return;

    const builderSocket: BuilderSocket = io(`${SOCKET_URL}/npc-builder`, {
      transports: ["websocket"],
      autoConnect: true,
      forceNew: true,
    });

    socketRef.current = builderSocket;

    builderSocket.on("connect", () => {
      setConnected(true);
      builderSocket.emit("init_npc_builder", { world_name: worldName });
    });

    builderSocket.on("disconnect", () => {
      setConnected(false);
      setSessionReady(false);
    });

    builderSocket.on("npc_builder_session_ready", () => {
      setSessionReady(true);
    });

    builderSocket.on("npc_builder_token", ({ token }: NPCBuilderTokenPayload) => {
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === "assistant" && last.streaming) {
          return [
            ...prev.slice(0, -1),
            { ...last, content: last.content + token },
          ];
        }
        return [...prev, { role: "assistant", content: token, streaming: true }];
      });
    });

    builderSocket.on("npc_builder_created", ({ name }: NPCBuilderCreatedPayload) => {
      setCreatedName(name);
    });

    builderSocket.on("npc_builder_done", () => {
      setStreaming(false);
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === "assistant" && last.streaming) {
          return [...prev.slice(0, -1), { ...last, streaming: false }];
        }
        return prev;
      });
    });

    builderSocket.on("error", ({ message }: SocketErrorPayload) => {
      console.error("NPC Builder socket error:", message);
      setError(message);
      setStreaming(false);
    });

    return () => {
      builderSocket.disconnect();
      socketRef.current = null;
    };
  }, [worldName]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, createdName]);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || !socketRef.current?.connected || streaming) return;

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setStreaming(true);
    setError(null);
    setCreatedName(null);
    socketRef.current.emit("npc_builder_message", { content: text });
  }, [input, streaming]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  if (!worldName) {
    return (
      <div className="npc-builder-page">
        <div className="npc-builder-container">
          <div className="npc-builder-header">
            <button
              type="button"
              className="btn btn-sm btn-outline"
              onClick={() => navigate("/npcs")}
            >
              Back to NPCs
            </button>
            <h2 className="npc-builder-title">NPC Builder</h2>
          </div>

          <div className="npc-builder-world-picker">
            <h3 className="text-base font-semibold text-base-content">
              Select a World
            </h3>
            <p className="text-sm text-base-content/60">
              Choose a lore world for the AI to draw from when building your NPC.
            </p>

            {worldError && (
              <div className="rounded-lg bg-error/10 px-4 py-2 text-sm text-error">
                {worldError}
              </div>
            )}

            {loadingWorlds && (
              <p className="py-4 text-center text-sm text-base-content/40">
                Loading worlds...
              </p>
            )}

            {!loadingWorlds && !worldError && worlds.length === 0 && (
              <p className="py-4 text-center text-sm text-base-content/40">
                No worlds found. Create one in the Lore section first.
              </p>
            )}

            {!loadingWorlds && worlds.length > 0 && (
              <div className="flex flex-col gap-1 pt-2">
                {worlds.map((w) => (
                  <button
                    key={w.name}
                    type="button"
                    className="npc-builder-world-btn btn btn-sm btn-ghost justify-start"
                    onClick={() => setSearchParams({ world: w.name })}
                  >
                    {w.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="npc-builder-page">
      <div className="npc-builder-container">
        <div className="npc-builder-header">
          <button
            type="button"
            className="btn btn-sm btn-outline"
            onClick={() => navigate("/npcs")}
          >
            Back to NPCs
          </button>
          <h2 className="npc-builder-title">NPC Builder &mdash; {worldName}</h2>
          <span
            className={`npc-builder-status ${connected && sessionReady ? "online" : "offline"}`}
          >
            {connected && sessionReady ? "Connected" : "Connecting..."}
          </span>
        </div>

        {error && <div className="npc-builder-error">{error}</div>}

        <div className="npc-builder-messages">
          {messages.length === 0 && (
            <p className="npc-builder-empty">
              Describe the NPC you want to create. The builder will use the
              world&apos;s lore to design a fitting character in W++ format.
            </p>
          )}
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`npc-builder-bubble ${msg.role === "user" ? "user" : "assistant"}`}
            >
              <span className="npc-builder-role">
                {msg.role === "user" ? "You" : "NPC Builder"}
              </span>
              <div className="npc-builder-content">{msg.content}</div>
            </div>
          ))}
          {createdName && (
            <div className="npc-builder-created">
              NPC &ldquo;{createdName}&rdquo; created successfully!
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="npc-builder-input-bar">
          <textarea
            className="textarea textarea-sm npc-builder-textarea"
            placeholder={
              sessionReady
                ? "Describe the NPC you want to create..."
                : "Connecting..."
            }
            rows={2}
            value={input}
            disabled={!sessionReady || streaming}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={!input.trim() || !sessionReady || streaming}
            onClick={handleSend}
          >
            {streaming ? "..." : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default NPCBuilderChat;
