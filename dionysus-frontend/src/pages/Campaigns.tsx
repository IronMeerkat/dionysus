import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { restService } from "../services/restService";
import type { CampaignListItem } from "../types/rest";
import "./Campaigns.css";

const Campaigns = () => {
  const navigate = useNavigate();
  const [campaigns, setCampaigns] = useState<CampaignListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    restService
      .getCampaigns()
      .then(setCampaigns)
      .catch((err: Error) => {
        console.error("❌ Failed to load campaigns", err);
        setError("Could not load campaigns.");
      })
      .finally(() => setLoading(false));
  }, []);

  const openCampaign = useCallback(
    (id: number) => navigate(`/campaigns/${id}`),
    [navigate],
  );

  const handleDeleteCampaign = useCallback(
    async (e: React.MouseEvent, campaign: CampaignListItem) => {
      e.stopPropagation();
      const confirmed = window.confirm(
        `Delete campaign "${campaign.name}"? This will permanently remove all conversations, messages, and memories.`,
      );
      if (!confirmed) return;

      try {
        await restService.deleteCampaign(campaign.id);
        setCampaigns((prev) => prev.filter((c) => c.id !== campaign.id));
      } catch (err) {
        console.error("🔥 Failed to delete campaign", err);
        setError("Failed to delete campaign.");
      }
    },
    [],
  );

  if (loading) {
    return (
      <div className="campaigns-page">
        <p className="campaigns-loading">Loading campaigns...</p>
      </div>
    );
  }

  return (
    <div className="campaigns-page">
      <div className="campaigns-header">
        <h2 className="campaigns-title">Campaigns</h2>
        <button
          type="button"
          className="btn btn-primary btn-action"
          onClick={() => navigate("/campaigns/new")}
        >
          New Campaign
        </button>
      </div>

      {error && <div className="campaigns-error">{error}</div>}

      {campaigns.length === 0 && !error ? (
        <p className="campaigns-empty">No campaigns yet. Create one to get started.</p>
      ) : (
        <div className="campaigns-grid">
          {campaigns.map((c) => (
            <div
              key={c.id}
              className="campaign-card"
              role="button"
              tabIndex={0}
              onClick={() => openCampaign(c.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter") openCampaign(c.id);
              }}
            >
              <div className="campaign-card-top">
                <div className="campaign-card-name">{c.name}</div>
                <button
                  type="button"
                  className="campaign-card-delete-btn"
                  title="Delete campaign"
                  onClick={(e) => handleDeleteCampaign(e, c)}
                >
                  &times;
                </button>
              </div>
              <div className="campaign-card-lore">{c.lore_world}</div>
              <div className="campaign-card-meta">
                {c.conversation_count} conversation{c.conversation_count !== 1 ? "s" : ""}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default Campaigns;
