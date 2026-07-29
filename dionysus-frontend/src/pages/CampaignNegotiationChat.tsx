import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams, useNavigate } from "react-router";
import { io, Socket } from "socket.io-client";
import type {
  CampaignNegotiationServerToClientEvents,
  CampaignNegotiationClientToServerEvents,
  CampaignNegotiationTokenPayload,
  CampaignNegotiationUpdatedPayload,
  SocketErrorPayload,
} from "../types/socket";
import { restService } from "../services/restService";
import type { CampaignDetailResponse } from "../types/rest";
import "./CampaignNegotiationChat.css";

type NegotiationSocket = Socket<
  CampaignNegotiationServerToClientEvents,
  CampaignNegotiationClientToServerEvents
>;

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

const SOCKET_URL =
  import.meta.env.VITE_SOCKET_URL ?? `http://${window.location.hostname}:8000`;

const CampaignNegotiationChat = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const campaignIdParam = searchParams.get("campaign_id") ?? "";
  const campaignId = Number(campaignIdParam);
  const hasValidId = campaignIdParam !== "" && Number.isFinite(campaignId);

  const socketRef = useRef<NegotiationSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const [campaign, setCampaign] = useState<CampaignDetailResponse | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [connected, setConnected] = useState(false);
  const [sessionReady, setSessionReady] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [updatedSummary, setUpdatedSummary] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // ---- fetch campaign name for the header ----
  useEffect(() => {
    if (!hasValidId) return;
    restService
      .getCampaign(campaignId)
      .then(setCampaign)
      .catch((err: Error) => {
        console.error("❌ Failed to load campaign", err);
      });
  }, [campaignId, hasValidId]);

  // ---- connect socket on mount ----
  useEffect(() => {
    if (!hasValidId) return;

    const negotiationSocket: NegotiationSocket = io(`${SOCKET_URL}/campaign-negotiation`, {
      transports: ["websocket"],
      autoConnect: true,
      forceNew: true,
    });

    socketRef.current = negotiationSocket;

    negotiationSocket.on("connect", () => {
      console.log("🔌 CampaignNegotiationChat: connected to /campaign-negotiation namespace");
      setConnected(true);
      negotiationSocket.emit("init_campaign_negotiation_session", { campaign_id: campaignId });
    });

    negotiationSocket.on("disconnect", (reason) => {
      console.log("🔌 CampaignNegotiationChat: disconnected —", reason);
      setConnected(false);
      setSessionReady(false);
    });

    negotiationSocket.on("campaign_negotiation_session_ready", ({ campaign_id }) => {
      console.log("🤝 CampaignNegotiationChat: session ready for campaign", campaign_id);
      setSessionReady(true);
    });

    negotiationSocket.on("campaign_negotiation_token", ({ token }: CampaignNegotiationTokenPayload) => {
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

    negotiationSocket.on("campaign_negotiation_updated", ({ summary }: CampaignNegotiationUpdatedPayload) => {
      setUpdatedSummary(summary);
    });

    negotiationSocket.on("campaign_negotiation_done", () => {
      setStreaming(false);
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === "assistant" && last.streaming) {
          return [...prev.slice(0, -1), { ...last, streaming: false }];
        }
        return prev;
      });
    });

    negotiationSocket.on("error", ({ message }: SocketErrorPayload) => {
      console.error("❌ CampaignNegotiationChat socket error:", message);
      setError(message);
      setStreaming(false);
    });

    return () => {
      negotiationSocket.disconnect();
      socketRef.current = null;
    };
  }, [campaignId, hasValidId]);

  // ---- auto-scroll ----
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, updatedSummary]);

  // ---- send message ----
  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || !socketRef.current?.connected || streaming) return;

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setStreaming(true);
    setError(null);
    setUpdatedSummary(null);
    socketRef.current.emit("campaign_negotiation_message", { content: text });
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

  // ---- guard: no campaign ----
  if (!hasValidId) {
    return (
      <div className="campaign-negotiation-page">
        <div className="campaign-negotiation-container">
          <div className="campaign-negotiation-header">
            <button
              type="button"
              className="btn btn-sm btn-outline"
              onClick={() => navigate("/campaigns")}
            >
              Back to Campaigns
            </button>
            <h2 className="campaign-negotiation-title">Campaign Negotiation</h2>
          </div>
          <p className="campaign-negotiation-empty">
            No campaign specified.{" "}
            <button
              type="button"
              className="btn btn-sm btn-link"
              onClick={() => navigate("/campaigns")}
            >
              Pick a campaign
            </button>
          </p>
        </div>
      </div>
    );
  }

  const headerName = campaign?.name ?? `#${campaignId}`;

  return (
    <div className="campaign-negotiation-page">
      <div className="campaign-negotiation-container">
        {/* ---- Header ---- */}
        <div className="campaign-negotiation-header">
          <button
            type="button"
            className="btn btn-sm btn-outline"
            onClick={() => navigate(`/campaigns/${campaignId}`)}
          >
            Back to Campaign
          </button>
          <h2 className="campaign-negotiation-title">Campaign Negotiation &mdash; {headerName}</h2>
          <span
            className={`campaign-negotiation-status ${connected && sessionReady ? "online" : "offline"}`}
          >
            {connected && sessionReady ? "Connected" : "Connecting..."}
          </span>
        </div>

        {error && <div className="campaign-negotiation-error">{error}</div>}

        {/* ---- Messages ---- */}
        <div className="campaign-negotiation-messages">
          {messages.length === 0 && (
            <p className="campaign-negotiation-empty">
              Negotiate what this campaign will be: the premise, the tone &amp;
              content contract, the starting situation, and the custom
              mechanics in play. Nothing is saved until you approve it.
            </p>
          )}
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`campaign-negotiation-bubble ${msg.role === "user" ? "user" : "assistant"}`}
            >
              <span className="campaign-negotiation-role">
                {msg.role === "user" ? "You" : "Negotiator"}
              </span>
              <div className="campaign-negotiation-content">{msg.content}</div>
            </div>
          ))}
          {updatedSummary && (
            <div className="campaign-negotiation-updated">{updatedSummary}</div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* ---- Input ---- */}
        <div className="campaign-negotiation-input-bar">
          <textarea
            className="textarea textarea-sm campaign-negotiation-textarea"
            placeholder={
              sessionReady
                ? "Describe the campaign you want, or ask about mechanics..."
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

export default CampaignNegotiationChat;
