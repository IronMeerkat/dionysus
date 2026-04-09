import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";
import "./Lore.css";
import { restService } from "../services/restService";
import type { WorldResponse, VectorMemoryApi } from "../types/rest";
import VectorMemoryWorld from "../components/VectorMemoryWorld";

const Lore = () => {
  const navigate = useNavigate();

  // ---- worlds ----
  const [worlds, setWorlds] = useState<WorldResponse[]>([]);
  const [selectedWorld, setSelectedWorld] = useState<string | null>(null);
  const [worldFormOpen, setWorldFormOpen] = useState(false);
  const [newWorldName, setNewWorldName] = useState("");

  // ---- loading / errors ----
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ---- fetch worlds on mount ----
  useEffect(() => {
    restService
      .getWorlds()
      .then((w) => {
        setWorlds(w);
        if (w.length > 0) setSelectedWorld(w[0].name);
      })
      .catch((err) => {
        console.error("❌ Failed to fetch worlds:", err);
        setError("Could not load worlds.");
      })
      .finally(() => setLoading(false));
  }, []);

  // ---- world CRUD ----
  const handleCreateWorld = useCallback(async () => {
    if (!newWorldName.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const created = await restService.createWorld(newWorldName.trim());
      setWorlds((prev) => [...prev, created]);
      setSelectedWorld(created.name);
      setNewWorldName("");
      setWorldFormOpen(false);
    } catch (err) {
      console.error("❌ Failed to create world:", err);
      setError("Could not create world.");
    } finally {
      setSaving(false);
    }
  }, [newWorldName]);

  const handleDeleteWorld = useCallback(async () => {
    if (selectedWorld === null) return;
    if (!confirm(`Delete world "${selectedWorld}" and all its entries?`)) return;
    setError(null);
    try {
      await restService.deleteWorld(selectedWorld);
      setWorlds((prev) => prev.filter((w) => w.name !== selectedWorld));
      setSelectedWorld(null);
    } catch (err) {
      console.error("❌ Failed to delete world:", err);
      setError("Could not delete world.");
    }
  }, [selectedWorld]);

  const loreApi: VectorMemoryApi = useMemo(
    () => ({
      getEntries: () => restService.getWorldEntries(selectedWorld!),
      getEntry: (uuid: string) => restService.getEntry(uuid),
      createEntry: (title: string, content: string) =>
        restService.createEntry(selectedWorld!, title, content),
      updateEntry: (uuid: string, title: string, content: string) =>
        restService.updateEntry(uuid, title, content),
      deleteEntry: (uuid: string) => restService.deleteEntry(uuid),
    }),
    [selectedWorld],
  );

  // ---- render ----

  if (loading) {
    return (
      <div className="lore-page">
        <p className="lore-loading">Loading worlds...</p>
      </div>
    );
  }

  return (
    <div className="lore-page">
      <div className="lore-container">
        {error && <div className="lore-error">{error}</div>}

        {/* ---- World Selector ---- */}
        <div className="lore-section">
          <div className="lore-section-header">
            <h2 className="lore-section-title">World</h2>
            <div className="lore-section-actions">
              <button
                type="button"
                className="btn btn-sm btn-outline btn-primary"
                onClick={() => setWorldFormOpen((v) => !v)}
              >
                {worldFormOpen ? "Cancel" : "+ New World"}
              </button>
              {selectedWorld !== null && (
                <>
                  <button
                    type="button"
                    className="btn btn-sm btn-outline btn-secondary"
                    onClick={() =>
                      navigate(
                        `/lore-chat?world=${encodeURIComponent(selectedWorld)}`,
                      )
                    }
                  >
                    AI Assistant
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-outline btn-error"
                    onClick={handleDeleteWorld}
                  >
                    Delete
                  </button>
                </>
              )}
            </div>
          </div>

          {worldFormOpen && (
            <div className="lore-world-form">
              <input
                type="text"
                className="input input-sm w-full"
                placeholder="World name"
                value={newWorldName}
                onChange={(e) => setNewWorldName(e.target.value)}
              />
              <button
                type="button"
                className="btn btn-sm btn-primary"
                disabled={!newWorldName.trim() || saving}
                onClick={handleCreateWorld}
              >
                {saving ? "Creating..." : "Create"}
              </button>
            </div>
          )}

          {worlds.length > 0 ? (
            <select
              className="select select-sm w-full"
              value={selectedWorld ?? ""}
              onChange={(e) =>
                setSelectedWorld(e.target.value || null)
              }
            >
              <option value="" disabled>
                Select a world
              </option>
              {worlds.map((w) => (
                <option key={w.name} value={w.name}>
                  {w.name} ({w.entry_count} entries)
                </option>
              ))}
            </select>
          ) : (
            !worldFormOpen && (
              <p className="lore-empty">
                No worlds yet. Create one to get started.
              </p>
            )
          )}
        </div>

        {/* ---- Entries ---- */}
        {selectedWorld !== null && (
          <VectorMemoryWorld api={loreApi} />
        )}
      </div>
    </div>
  );
};

export default Lore;
