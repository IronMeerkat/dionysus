import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { restService } from "../services/restService";
import type { WorldResponse } from "../types/rest";
import "./CreateCampaign.css";

const CreateCampaign = () => {
  const navigate = useNavigate();

  const [name, setName] = useState("");
  const [selectedWorld, setSelectedWorld] = useState("");
  const [worlds, setWorlds] = useState<WorldResponse[]>([]);

  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    restService
      .getWorlds()
      .then((w) => {
        setWorlds(w);
        if (w.length === 1) setSelectedWorld(w[0].name);
      })
      .catch((err: Error) => {
        console.error("❌ Failed to load lore worlds", err);
        setError("Could not load lore worlds.");
      })
      .finally(() => setLoading(false));
  }, []);

  const canSubmit = name.trim().length > 0 && selectedWorld.length > 0 && !submitting;

  const handleSubmit = useCallback(async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const campaign = await restService.createCampaign(name.trim(), selectedWorld);
      navigate(`/campaigns/${campaign.id}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      console.error("❌ Failed to create campaign", err);
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }, [canSubmit, name, selectedWorld, navigate]);

  if (loading) {
    return (
      <div className="create-campaign">
        <p className="create-campaign-loading">Loading lore worlds...</p>
      </div>
    );
  }

  return (
    <div className="create-campaign">
      <div className="create-campaign-card">
        <h2 className="create-campaign-title">New Campaign</h2>

        {error && <div className="create-campaign-error">{error}</div>}

        <div className="create-campaign-field">
          <label className="create-campaign-label" htmlFor="campaign-name">
            Campaign Name
          </label>
          <input
            id="campaign-name"
            className="create-campaign-input"
            type="text"
            placeholder="Enter a name..."
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <div className="create-campaign-field">
          <label className="create-campaign-label" htmlFor="lore-world">
            Lore World
          </label>
          <select
            id="lore-world"
            className="create-campaign-select"
            value={selectedWorld}
            onChange={(e) => setSelectedWorld(e.target.value)}
          >
            <option value="" disabled>
              Select a lore world...
            </option>
            {worlds.map((w) => (
              <option key={w.name} value={w.name}>
                {w.name} ({w.entry_count} entries)
              </option>
            ))}
          </select>
        </div>

        <div className="create-campaign-footer">
          <button
            type="button"
            className="btn btn-primary btn-action"
            disabled={!canSubmit}
            onClick={handleSubmit}
          >
            {submitting ? "Creating..." : "Create Campaign"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default CreateCampaign;
