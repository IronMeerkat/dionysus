import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams, useNavigate } from "react-router";
import { io, Socket } from "socket.io-client";
import type {
  LoreServerToClientEvents,
  LoreClientToServerEvents,
  LoreTokenPayload,
  LoreSavingPayload,
  SocketErrorPayload,
} from "../types/socket";
import "./LoreChat.css";

type LoreSocket = Socket<LoreServerToClientEvents, LoreClientToServerEvents>;

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

const SOCKET_URL =
  import.meta.env.VITE_SOCKET_URL ?? `http://${window.location.hostname}:8000`;

const LoreChat = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const worldName = searchParams.get("world") ?? "";

  const socketRef = useRef<LoreSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [connected, setConnected] = useState(false);
  const [sessionReady, setSessionReady] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [savingTitle, setSavingTitle] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // ---- connect socket on mount ----
  useEffect(() => {
    if (!worldName) return;

    const loreSocket: LoreSocket = io(`${SOCKET_URL}/lore`, {
      transports: ["websocket"],
      autoConnect: true,
      forceNew: true,
    });

    socketRef.current = loreSocket;

    loreSocket.on("connect", () => {
      console.log("🔌 LoreChat: connected to /lore namespace");
      setConnected(true);
      loreSocket.emit("init_lore_session", { world_name: worldName });
    });

    loreSocket.on("disconnect", (reason) => {
      console.log("🔌 LoreChat: disconnected —", reason);
      setConnected(false);
      setSessionReady(false);
    });

    loreSocket.on("lore_session_ready", () => {
      console.log("🌍 LoreChat: session ready for", worldName);
      setSessionReady(true);
    });

    loreSocket.on("lore_token", ({ token }: LoreTokenPayload) => {
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

    loreSocket.on("lore_saving", ({ title }: LoreSavingPayload) => {
      setSavingTitle(title);
    });

    loreSocket.on("lore_done", () => {
      setStreaming(false);
      setSavingTitle(null);
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === "assistant" && last.streaming) {
          return [...prev.slice(0, -1), { ...last, streaming: false }];
        }
        return prev;
      });
    });

    loreSocket.on("error", ({ message }: SocketErrorPayload) => {
      console.error("❌ LoreChat socket error:", message);
      setError(message);
      setStreaming(false);
    });

    return () => {
      loreSocket.disconnect();
      socketRef.current = null;
    };
  }, [worldName]);

  // ---- auto-scroll ----
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, savingTitle]);

  // ---- send message ----
  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || !socketRef.current?.connected || streaming) return;

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setStreaming(true);
    setError(null);
    socketRef.current.emit("lore_message", { content: text });
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

  // ---- guard: no world ----
  if (!worldName) {
    return (
      <div className="lore-chat-page">
        <div className="lore-chat-container">
          <p className="lore-chat-empty">
            No world specified.{" "}
            <button
              type="button"
              className="btn btn-sm btn-link"
              onClick={() => navigate("/lore")}
            >
              Back to Lore
            </button>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="lore-chat-page">
      <div className="lore-chat-container">
        {/* ---- Header ---- */}
        <div className="lore-chat-header">
          <button
            type="button"
            className="btn btn-sm btn-outline"
            onClick={() => navigate("/lore")}
          >
            Back to Lore
          </button>
          <h2 className="lore-chat-title">Lore Assistant — {worldName}</h2>
          <span
            className={`lore-chat-status ${connected && sessionReady ? "online" : "offline"}`}
          >
            {connected && sessionReady ? "Connected" : "Connecting..."}
          </span>
        </div>

        {error && <div className="lore-chat-error">{error}</div>}

        {/* ---- Messages ---- */}
        <div className="lore-chat-messages">
          {messages.length === 0 && (
            <p className="lore-chat-empty">
              Describe the lore you want to create or edit.
            </p>
          )}
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`lore-chat-bubble ${msg.role === "user" ? "user" : "assistant"}`}
            >
              <span className="lore-chat-role">
                {msg.role === "user" ? "You" : "Lore Assistant"}
              </span>
              <div className="lore-chat-content">{msg.content}</div>
            </div>
          ))}
          {savingTitle && (
            <div className="lore-chat-saving">
              Saving &ldquo;{savingTitle}&rdquo; to knowledge graph...
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* ---- Input ---- */}
        <div className="lore-chat-input-bar">
          <textarea
            className="textarea textarea-sm lore-chat-textarea"
            placeholder={
              sessionReady
                ? "Describe lore to create or edit..."
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

export default LoreChat;
