import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router";
import "./Lore.css";
import { restService } from "../services/restService";
import type {
  WorldResponse,
  LoreEntryListItem,
  LoreEntryResponse,
} from "../types/rest";

type EditorMode = "idle" | "create" | "edit";

interface EntryDraft {
  title: string;
  content: string;
}

const EMPTY_DRAFT: EntryDraft = { title: "", content: "" };

const Lore = () => {
  const navigate = useNavigate();

  // ---- worlds ----
  const [worlds, setWorlds] = useState<WorldResponse[]>([]);
  const [selectedWorld, setSelectedWorld] = useState<string | null>(null);
  const [worldFormOpen, setWorldFormOpen] = useState(false);
  const [newWorldName, setNewWorldName] = useState("");

  // ---- entries ----
  const [entries, setEntries] = useState<LoreEntryListItem[]>([]);
  const [selectedEntryUuid, setSelectedEntryUuid] = useState<string | null>(null);

  // ---- editor ----
  const [editorMode, setEditorMode] = useState<EditorMode>("idle");
  const [draft, setDraft] = useState<EntryDraft>(EMPTY_DRAFT);

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
        console.error("Failed to fetch worlds", err);
        setError("Could not load worlds.");
      })
      .finally(() => setLoading(false));
  }, []);

  // ---- fetch entries when world changes ----
  useEffect(() => {
    if (selectedWorld === null) {
      setEntries([]);
      return;
    }
    restService
      .getWorldEntries(selectedWorld)
      .then(setEntries)
      .catch((err) => {
        console.error("Failed to fetch entries", err);
        setError("Could not load entries.");
      });
  }, [selectedWorld]);

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
      console.error("Failed to create world", err);
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
      setEntries([]);
      resetEditor();
    } catch (err) {
      console.error("Failed to delete world", err);
      setError("Could not delete world.");
    }
  }, [selectedWorld]);

  // ---- entry selection ----
  const handleSelectEntry = useCallback(async (uuid: string) => {
    setError(null);
    try {
      const full: LoreEntryResponse = await restService.getEntry(uuid);
      setSelectedEntryUuid(full.uuid);
      setDraft({
        title: full.title,
        content: full.content,
      });
      setEditorMode("edit");
    } catch (err) {
      console.error("Failed to load entry", err);
      setError("Could not load entry.");
    }
  }, []);

  // ---- editor helpers ----
  const resetEditor = useCallback(() => {
    setEditorMode("idle");
    setSelectedEntryUuid(null);
    setDraft(EMPTY_DRAFT);
  }, []);

  const handleNewEntry = useCallback(() => {
    setSelectedEntryUuid(null);
    setDraft(EMPTY_DRAFT);
    setEditorMode("create");
  }, []);

  const handleSave = useCallback(async () => {
    if (selectedWorld === null) return;
    if (!draft.title.trim() || !draft.content.trim()) return;
    setSaving(true);
    setError(null);
    try {
      if (editorMode === "create") {
        const created = await restService.createEntry(
          selectedWorld,
          draft.title.trim(),
          draft.content.trim(),
        );
        setEntries((prev) => [
          ...prev,
          {
            uuid: created.uuid,
            title: created.title,
            created_at: created.created_at,
          },
        ]);
        setSelectedEntryUuid(created.uuid);
        setEditorMode("edit");
      } else if (editorMode === "edit" && selectedEntryUuid !== null) {
        const updated = await restService.updateEntry(
          selectedEntryUuid,
          draft.title.trim(),
          draft.content.trim(),
        );
        setEntries((prev) =>
          prev.map((e) =>
            e.uuid === selectedEntryUuid
              ? {
                  uuid: updated.uuid,
                  title: updated.title,
                  created_at: updated.created_at,
                }
              : e,
          ),
        );
        setSelectedEntryUuid(updated.uuid);
      }
    } catch (err) {
      console.error("Failed to save entry", err);
      setError("Could not save entry.");
    } finally {
      setSaving(false);
    }
  }, [selectedWorld, editorMode, selectedEntryUuid, draft]);

  const handleDeleteEntry = useCallback(async () => {
    if (selectedEntryUuid === null) return;
    if (!confirm("Delete this lore entry?")) return;
    setError(null);
    try {
      await restService.deleteEntry(selectedEntryUuid);
      setEntries((prev) => prev.filter((e) => e.uuid !== selectedEntryUuid));
      resetEditor();
    } catch (err) {
      console.error("Failed to delete entry", err);
      setError("Could not delete entry.");
    }
  }, [selectedEntryUuid, resetEditor]);

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
                      navigate(`/lore-chat?world=${encodeURIComponent(selectedWorld)}`)
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
              onChange={(e) => {
                setSelectedWorld(e.target.value || null);
                resetEditor();
              }}
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
              <p className="lore-empty">No worlds yet. Create one to get started.</p>
            )
          )}
        </div>

        {/* ---- Entries List ---- */}
        {selectedWorld !== null && (
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
                    key={entry.uuid}
                    type="button"
                    className={`lore-entry-row ${selectedEntryUuid === entry.uuid ? "selected" : ""}`}
                    onClick={() => handleSelectEntry(entry.uuid)}
                  >
                    <span className="lore-entry-title">{entry.title}</span>
                  </button>
                ))}
              </div>
            ) : (
              <p className="lore-empty">No entries in this world yet.</p>
            )}
          </div>
        )}

        {/* ---- Entry Editor ---- */}
        {editorMode !== "idle" && selectedWorld !== null && (
          <div className="lore-section">
            <div className="lore-section-header">
              <h2 className="lore-section-title">
                {editorMode === "create" ? "New Entry" : "Edit Entry"}
              </h2>
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
                {editorMode === "edit" && selectedEntryUuid !== null && (
                  <button
                    type="button"
                    className="btn btn-sm btn-error"
                    onClick={handleDeleteEntry}
                  >
                    Delete
                  </button>
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
