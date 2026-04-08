import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { restService } from "../services/restService";
import { useConversationStore } from "../contexts/ConversationStore";
import { useSessionStore } from "../contexts/SessionStore";
import { useMessageStore } from "../contexts/MessageStore";
import type { CampaignDetailResponse } from "../types/rest";
import "./CampaignDetail.css";

const CampaignDetail = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { setActiveConversation } = useConversationStore();
  const { setPlayer, setCharacters } = useSessionStore();
  const setMessages = useMessageStore((s) => s.setMessages);

  const [campaign, setCampaign] = useState<CampaignDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    if (!id) return;
    restService
      .getCampaign(Number(id))
      .then(setCampaign)
      .catch((err: Error) => {
        console.error("❌ Failed to load campaign", err);
        setError("Could not load campaign.");
      })
      .finally(() => setLoading(false));
  }, [id]);

  const openConversation = useCallback(
    async (conversationId: number) => {
      try {
        const res = await restService.loadConversation(conversationId);
        setActiveConversation(conversationId, res.title);
        setPlayer(res.player);
        setCharacters(res.characters);
        setMessages(
          res.messages.map((m) => ({
            id: m.id,
            content: m.content,
            role: m.role,
            name: m.name,
            createdAt: new Date(m.created_at),
          })),
        );
        navigate("/");
      } catch (err) {
        console.error("🔥 Failed to load conversation", err);
      }
    },
    [navigate, setActiveConversation, setPlayer, setCharacters, setMessages],
  );

  const handleDeleteCampaign = useCallback(async () => {
    if (!campaign) return;
    const confirmed = window.confirm(
      `Delete campaign "${campaign.name}"? This will permanently remove all conversations, messages, and memories.`,
    );
    if (!confirmed) return;

    setDeleting(true);
    try {
      await restService.deleteCampaign(campaign.id);
      navigate("/campaigns");
    } catch (err) {
      console.error("🔥 Failed to delete campaign", err);
      setError("Failed to delete campaign.");
      setDeleting(false);
    }
  }, [campaign, navigate]);

  const handleDeleteConversation = useCallback(
    async (conversationId: number, title: string) => {
      const confirmed = window.confirm(`Delete conversation "${title}"?`);
      if (!confirmed || !campaign) return;

      try {
        await restService.deleteConversation(conversationId);
        setCampaign({
          ...campaign,
          conversations: campaign.conversations.filter((c) => c.id !== conversationId),
        });
      } catch (err) {
        console.error("🔥 Failed to delete conversation", err);
        setError("Failed to delete conversation.");
      }
    },
    [campaign],
  );

  if (loading) {
    return (
      <div className="campaign-detail">
        <p className="campaign-detail-loading">Loading campaign...</p>
      </div>
    );
  }

  if (!campaign) {
    return (
      <div className="campaign-detail">
        <div className="campaign-detail-error">{error ?? "Campaign not found."}</div>
      </div>
    );
  }

  return (
    <div className="campaign-detail">
      <div className="campaign-detail-header">
        <div>
          <h2 className="campaign-detail-name">{campaign.name}</h2>
          <span className="campaign-detail-lore">{campaign.lore_world}</span>
        </div>
        <button
          type="button"
          className="btn btn-error btn-outline btn-sm campaign-delete-btn"
          disabled={deleting}
          onClick={handleDeleteCampaign}
        >
          {deleting ? "Deleting..." : "Delete Campaign"}
        </button>
      </div>

      {error && <div className="campaign-detail-error">{error}</div>}

      <div className="campaign-detail-section-header">
        <h3 className="campaign-detail-section-title">Conversations</h3>
        <button
          type="button"
          className="btn btn-primary btn-action btn-sm"
          onClick={() => navigate(`/session-setup?campaign_id=${campaign.id}`)}
        >
          New Conversation
        </button>
      </div>

      {campaign.conversations.length === 0 ? (
        <p className="campaign-detail-empty">
          No conversations yet. Start one to begin your adventure.
        </p>
      ) : (
        <div className="campaign-detail-grid">
          {campaign.conversations.map((conv) => (
            <div
              key={conv.id}
              className="campaign-conv-card"
              role="button"
              tabIndex={0}
              onClick={() => openConversation(conv.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter") openConversation(conv.id);
              }}
            >
              <div className="campaign-conv-card-top">
                <div className="campaign-conv-title">{conv.title}</div>
                <button
                  type="button"
                  className="campaign-conv-delete-btn"
                  title="Delete conversation"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDeleteConversation(conv.id, conv.title);
                  }}
                >
                  &times;
                </button>
              </div>
              <div className="campaign-conv-date">
                {new Date(conv.created_at).toLocaleDateString()}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default CampaignDetail;
