import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router";
import "./Lore.css";
import { restService } from "../services/restService";
import type {
  WorldResponse,
  LoreEntryListItem,
  LoreEntryResponse,
  IngestionStatus,
} from "../types/rest";

const CATEGORIES = [
  "character",
  "location",
  "organization",
  "nation",
  "race",
  "concept",
  "creature",
  "item",
  "event",
  "general",
] as const;

type EditorMode = "idle" | "create" | "edit";

interface EntryDraft {
  title: string;
  content: string;
  category: string;
}

const EMPTY_DRAFT: EntryDraft = { title: "", content: "", category: "general" };

const STATUS_STYLES: Record<IngestionStatus, string> = {
  pending: "badge badge-warning badge-sm",
  ingested: "badge badge-success badge-sm",
  failed: "badge badge-error badge-sm",
};

const STATUS_LABELS: Record<IngestionStatus, string> = {
  pending: "Pending",
  ingested: "Ingested",
  failed: "Failed",
};

const Lore = () => {
  const navigate = useNavigate();

  // ---- worlds ----
  const [worlds, setWorlds] = useState<WorldResponse[]>([]);
  const [selectedWorldId, setSelectedWorldId] = useState<number | null>(null);
  const [worldFormOpen, setWorldFormOpen] = useState(false);
  const [newWorldName, setNewWorldName] = useState("");
  const [newWorldDesc, setNewWorldDesc] = useState("");

  // ---- entries ----
  const [entries, setEntries] = useState<LoreEntryListItem[]>([]);
  const [selectedEntryId, setSelectedEntryId] = useState<number | null>(null);

  // ---- editor ----
  const [editorMode, setEditorMode] = useState<EditorMode>("idle");
  const [draft, setDraft] = useState<EntryDraft>(EMPTY_DRAFT);

  // ---- ingestion status for selected entry ----
  const [selectedIngestionStatus, setSelectedIngestionStatus] =
    useState<IngestionStatus>("pending");
  const [reingesting, setReingesting] = useState(false);

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
        if (w.length > 0) setSelectedWorldId(w[0].id);
      })
      .catch((err) => {
        console.error("Failed to fetch worlds", err);
        setError("Could not load worlds.");
      })
      .finally(() => setLoading(false));
  }, []);

  // ---- fetch entries when world changes ----
  useEffect(() => {
    if (selectedWorldId === null) {
      setEntries([]);
      return;
    }
    restService
      .getWorldEntries(selectedWorldId)
      .then(setEntries)
      .catch((err) => {
        console.error("Failed to fetch entries", err);
        setError("Could not load entries.");
      });
  }, [selectedWorldId]);

  // ---- world CRUD ----
  const handleCreateWorld = useCallback(async () => {
    if (!newWorldName.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const created = await restService.createWorld(
        newWorldName.trim(),
        newWorldDesc.trim(),
      );
      setWorlds((prev) => [...prev, created]);
      setSelectedWorldId(created.id);
      setNewWorldName("");
      setNewWorldDesc("");
      setWorldFormOpen(false);
    } catch (err) {
      console.error("Failed to create world", err);
      setError("Could not create world.");
    } finally {
      setSaving(false);
    }
  }, [newWorldName, newWorldDesc]);

  const handleDeleteWorld = useCallback(async () => {
    if (selectedWorldId === null) return;
    const world = worlds.find((w) => w.id === selectedWorldId);
    if (!world) return;
    if (!confirm(`Delete world "${world.name}" and all its entries?`)) return;
    setError(null);
    try {
      await restService.deleteWorld(selectedWorldId);
      setWorlds((prev) => prev.filter((w) => w.id !== selectedWorldId));
      setSelectedWorldId(null);
      setEntries([]);
      resetEditor();
    } catch (err) {
      console.error("Failed to delete world", err);
      setError("Could not delete world.");
    }
  }, [selectedWorldId, worlds]);

  // ---- entry selection ----
  const handleSelectEntry = useCallback(
    async (entryId: number) => {
      setError(null);
      try {
        const full: LoreEntryResponse = await restService.getEntry(entryId);
        setSelectedEntryId(full.id);
        setSelectedIngestionStatus(full.ingestion_status);
        setDraft({
          title: full.title,
          content: full.content,
          category: full.category ?? "general",
        });
        setEditorMode("edit");
      } catch (err) {
        console.error("Failed to load entry", err);
        setError("Could not load entry.");
      }
    },
    [],
  );

  // ---- editor helpers ----
  const resetEditor = useCallback(() => {
    setEditorMode("idle");
    setSelectedEntryId(null);
    setDraft(EMPTY_DRAFT);
    setSelectedIngestionStatus("pending");
    setReingesting(false);
  }, []);

  const handleNewEntry = useCallback(() => {
    setSelectedEntryId(null);
    setDraft(EMPTY_DRAFT);
    setEditorMode("create");
  }, []);

  const handleSave = useCallback(async () => {
    if (selectedWorldId === null) return;
    if (!draft.title.trim() || !draft.content.trim()) return;
    setSaving(true);
    setError(null);
    try {
      if (editorMode === "create") {
        const created = await restService.createEntry(
          selectedWorldId,
          draft.title.trim(),
          draft.content.trim(),
          draft.category || null,
        );
        setEntries((prev) => [
          ...prev,
          {
            id: created.id,
            title: created.title,
            category: created.category,
            ingestion_status: created.ingestion_status,
            created_at: created.created_at,
            updated_at: created.updated_at,
          },
        ]);
        setSelectedEntryId(created.id);
        setSelectedIngestionStatus(created.ingestion_status);
        setEditorMode("edit");
      } else if (editorMode === "edit" && selectedEntryId !== null) {
        const updated = await restService.updateEntry(
          selectedEntryId,
          draft.title.trim(),
          draft.content.trim(),
          draft.category || null,
        );
        setEntries((prev) =>
          prev.map((e) =>
            e.id === updated.id
              ? {
                  id: updated.id,
                  title: updated.title,
                  category: updated.category,
                  ingestion_status: updated.ingestion_status,
                  created_at: updated.created_at,
                  updated_at: updated.updated_at,
                }
              : e,
          ),
        );
      }
    } catch (err) {
      console.error("Failed to save entry", err);
      setError("Could not save entry.");
    } finally {
      setSaving(false);
    }
  }, [selectedWorldId, editorMode, selectedEntryId, draft]);

  const handleReingest = useCallback(async () => {
    if (selectedEntryId === null) return;
    setReingesting(true);
    setError(null);
    try {
      const updated = await restService.reingestEntry(selectedEntryId);
      setSelectedIngestionStatus(updated.ingestion_status);
      setEntries((prev) =>
        prev.map((e) =>
          e.id === updated.id
            ? { ...e, ingestion_status: updated.ingestion_status }
            : e,
        ),
      );
    } catch (err) {
      console.error("Failed to reingest entry", err);
      setError("Could not re-trigger ingestion.");
    } finally {
      setReingesting(false);
    }
  }, [selectedEntryId]);

  const handleDeleteEntry = useCallback(async () => {
    if (selectedEntryId === null) return;
    if (!confirm("Delete this lore entry?")) return;
    setError(null);
    try {
      await restService.deleteEntry(selectedEntryId);
      setEntries((prev) => prev.filter((e) => e.id !== selectedEntryId));
      resetEditor();
    } catch (err) {
      console.error("Failed to delete entry", err);
      setError("Could not delete entry.");
    }
  }, [selectedEntryId, resetEditor]);

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
              {selectedWorldId !== null && (
                <>
                  <button
                    type="button"
                    className="btn btn-sm btn-outline btn-secondary"
                    onClick={() => {
                      const world = worlds.find((w) => w.id === selectedWorldId);
                      if (world) navigate(`/lore-chat?world=${encodeURIComponent(world.name)}`);
                    }}
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
              <input
                type="text"
                className="input input-sm w-full"
                placeholder="Description (optional)"
                value={newWorldDesc}
                onChange={(e) => setNewWorldDesc(e.target.value)}
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
              value={selectedWorldId ?? ""}
              onChange={(e) => {
                const val = Number(e.target.value);
                setSelectedWorldId(val || null);
                resetEditor();
              }}
            >
              <option value="" disabled>
                Select a world
              </option>
              {worlds.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name} ({w.entry_count} entries)
                </option>
              ))}
            </select>
          ) : (
            !worldFormOpen && (
              <p className="lore-empty">No worlds yet. Create one to get started.</p>
            )
          )}
        </div>

        {/* ---- Entries List ---- */}
        {selectedWorldId !== null && (
          <div className="lore-section">
            <div className="lore-section-header">
              <h2 className="lore-section-title">Entries</h2>
              <button
                type="button"
                className="btn btn-sm btn-outline btn-primary"
                onClick={handleNewEntry}
              >
                + New Entry
              </button>
            </div>

            {entries.length > 0 ? (
              <div className="lore-entries-list">
                {entries.map((entry) => (
                  <button
                    key={entry.id}
                    type="button"
                    className={`lore-entry-row ${selectedEntryId === entry.id ? "selected" : ""}`}
                    onClick={() => handleSelectEntry(entry.id)}
                  >
                    <span className="lore-entry-title">{entry.title}</span>
                    <span className="lore-entry-badges">
                      {entry.category && (
                        <span className="lore-entry-badge">{entry.category}</span>
                      )}
                      <span className={STATUS_STYLES[entry.ingestion_status]}>
                        {STATUS_LABELS[entry.ingestion_status]}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              <p className="lore-empty">No entries in this world yet.</p>
            )}
          </div>
        )}

        {/* ---- Entry Editor ---- */}
        {editorMode !== "idle" && selectedWorldId !== null && (
          <div className="lore-section">
            <div className="lore-section-header">
              <h2 className="lore-section-title">
                {editorMode === "create" ? "New Entry" : "Edit Entry"}
              </h2>
              {editorMode === "edit" && (
                <span className={STATUS_STYLES[selectedIngestionStatus]}>
                  {STATUS_LABELS[selectedIngestionStatus]}
                </span>
              )}
            </div>

            <div className="lore-editor-form">
              <label className="lore-label">
                Title
                <input
                  type="text"
                  className="input input-sm w-full"
                  value={draft.title}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, title: e.target.value }))
                  }
                />
              </label>

              <label className="lore-label">
                Category
                <select
                  className="select select-sm w-full"
                  value={draft.category}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, category: e.target.value }))
                  }
                >
                  {CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {c.charAt(0).toUpperCase() + c.slice(1)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="lore-label">
                Content
                <textarea
                  className="textarea textarea-sm w-full lore-textarea"
                  rows={12}
                  value={draft.content}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, content: e.target.value }))
                  }
                />
              </label>

              <div className="lore-editor-actions">
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  disabled={
                    !draft.title.trim() || !draft.content.trim() || saving
                  }
                  onClick={handleSave}
                >
                  {saving ? "Saving..." : "Save"}
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-outline"
                  onClick={resetEditor}
                >
                  Cancel
                </button>
                {editorMode === "edit" && selectedEntryId !== null && (
                  <>
                    {selectedIngestionStatus === "failed" && (
                      <button
                        type="button"
                        className="btn btn-sm btn-warning"
                        disabled={reingesting}
                        onClick={handleReingest}
                      >
                        {reingesting ? "Retrying..." : "Retry Ingestion"}
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn btn-sm btn-error"
                      onClick={handleDeleteEntry}
                    >
                      Delete
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default Lore;
