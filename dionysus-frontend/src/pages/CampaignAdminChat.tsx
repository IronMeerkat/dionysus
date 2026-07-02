import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams, useNavigate } from "react-router";
import { io, Socket } from "socket.io-client";
import type {
  CampaignAdminServerToClientEvents,
  CampaignAdminClientToServerEvents,
  CampaignAdminTokenPayload,
  CampaignAdminUpdatedPayload,
  SocketErrorPayload,
} from "../types/socket";
import { restService } from "../services/restService";
import type { CampaignDetailResponse } from "../types/rest";
import "./CampaignAdminChat.css";

type AdminSocket = Socket<
  CampaignAdminServerToClientEvents,
  CampaignAdminClientToServerEvents
>;

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
}

const SOCKET_URL =
  import.meta.env.VITE_SOCKET_URL ?? `http://${window.location.hostname}:8000`;

const CampaignAdminChat = () => {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const campaignIdParam = searchParams.get("campaign_id") ?? "";
  const campaignId = Number(campaignIdParam);
  const hasValidId = campaignIdParam !== "" && Number.isFinite(campaignId);

  const socketRef = useRef<AdminSocket | null>(null);
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

    const adminSocket: AdminSocket = io(`${SOCKET_URL}/campaign-admin`, {
      transports: ["websocket"],
      autoConnect: true,
      forceNew: true,
    });

    socketRef.current = adminSocket;

    adminSocket.on("connect", () => {
      console.log("🔌 CampaignAdminChat: connected to /campaign-admin namespace");
      setConnected(true);
      adminSocket.emit("init_campaign_admin_session", { campaign_id: campaignId });
    });

    adminSocket.on("disconnect", (reason) => {
      console.log("🔌 CampaignAdminChat: disconnected —", reason);
      setConnected(false);
      setSessionReady(false);
    });

    adminSocket.on("campaign_admin_session_ready", ({ campaign_id }) => {
      console.log("📋 CampaignAdminChat: session ready for campaign", campaign_id);
      setSessionReady(true);
    });

    adminSocket.on("campaign_admin_token", ({ token }: CampaignAdminTokenPayload) => {
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

    adminSocket.on("campaign_admin_updated", ({ summary }: CampaignAdminUpdatedPayload) => {
      setUpdatedSummary(summary);
    });

    adminSocket.on("campaign_admin_done", () => {
      setStreaming(false);
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === "assistant" && last.streaming) {
          return [...prev.slice(0, -1), { ...last, streaming: false }];
        }
        return prev;
      });
    });

    adminSocket.on("error", ({ message }: SocketErrorPayload) => {
      console.error("❌ CampaignAdminChat socket error:", message);
      setError(message);
      setStreaming(false);
    });

    return () => {
      adminSocket.disconnect();
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
    socketRef.current.emit("campaign_admin_message", { content: text });
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
      <div className="campaign-admin-page">
        <div className="campaign-admin-container">
          <div className="campaign-admin-header">
            <button
              type="button"
              className="btn btn-sm btn-outline"
              onClick={() => navigate("/campaigns")}
            >
              Back to Campaigns
            </button>
            <h2 className="campaign-admin-title">Campaign Admin</h2>
          </div>
          <p className="campaign-admin-empty">
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
    <div className="campaign-admin-page">
      <div className="campaign-admin-container">
        {/* ---- Header ---- */}
        <div className="campaign-admin-header">
          <button
            type="button"
            className="btn btn-sm btn-outline"
            onClick={() => navigate(`/campaigns/${campaignId}`)}
          >
            Back to Campaign
          </button>
          <h2 className="campaign-admin-title">Campaign Admin &mdash; {headerName}</h2>
          <span
            className={`campaign-admin-status ${connected && sessionReady ? "online" : "offline"}`}
          >
            {connected && sessionReady ? "Connected" : "Connecting..."}
          </span>
        </div>

        {error && <div className="campaign-admin-error">{error}</div>}

        {/* ---- Messages ---- */}
        <div className="campaign-admin-messages">
          {messages.length === 0 && (
            <p className="campaign-admin-empty">
              Talk out-of-character about this campaign&rsquo;s settings: the
              story background, tone &amp; content contract, current location,
              narrative clock, quest threads, and faction clocks.
            </p>
          )}
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`campaign-admin-bubble ${msg.role === "user" ? "user" : "assistant"}`}
            >
              <span className="campaign-admin-role">
                {msg.role === "user" ? "You" : "Campaign Admin"}
              </span>
              <div className="campaign-admin-content">{msg.content}</div>
            </div>
          ))}
          {updatedSummary && (
            <div className="campaign-admin-updated">{updatedSummary}</div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* ---- Input ---- */}
        <div className="campaign-admin-input-bar">
          <textarea
            className="textarea textarea-sm campaign-admin-textarea"
            placeholder={
              sessionReady
                ? "Ask or change something about the campaign..."
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

export default CampaignAdminChat;
