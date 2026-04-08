import { useCallback, useEffect, useState } from "react";
import type {
  EntityListItem,
  EntityDetailResponse,
  DescriptionVersion,
  MessageResponse,
} from "../types/rest";
import "./EntityManager.css";

type EditorMode = "idle" | "create" | "edit";

interface EntityDraft {
  name: string;
  description: string;
}

const EMPTY_DRAFT: EntityDraft = { name: "", description: "" };

interface EntityManagerApi {
  list: () => Promise<EntityListItem[]>;
  get: (id: number) => Promise<EntityDetailResponse>;
  create: (name: string, description: string) => Promise<EntityDetailResponse>;
  updateName: (id: number, name: string) => Promise<EntityDetailResponse>;
  addDescription: (id: number, body: string) => Promise<EntityDetailResponse>;
  remove: (id: number) => Promise<MessageResponse>;
}

interface EntityManagerProps {
  title: string;
  entityLabel: string;
  api: EntityManagerApi;
}

const EntityManager = ({ title, entityLabel, api }: EntityManagerProps) => {
  const [entities, setEntities] = useState<EntityListItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [descriptions, setDescriptions] = useState<DescriptionVersion[]>([]);

  const [editorMode, setEditorMode] = useState<EditorMode>("idle");
  const [draft, setDraft] = useState<EntityDraft>(EMPTY_DRAFT);
  const [originalName, setOriginalName] = useState("");

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .list()
      .then(setEntities)
      .catch((err) => {
        console.error(`❌ Failed to fetch ${entityLabel} list`, err);
        setError(`Could not load ${entityLabel}s.`);
      })
      .finally(() => setLoading(false));
  }, [api, entityLabel]);

  const resetEditor = useCallback(() => {
    setEditorMode("idle");
    setSelectedId(null);
    setDraft(EMPTY_DRAFT);
    setDescriptions([]);
    setOriginalName("");
  }, []);

  const handleSelect = useCallback(
    async (id: number) => {
      setError(null);
      try {
        const detail = await api.get(id);
        setSelectedId(detail.id);
        setOriginalName(detail.name);
        const latestBody =
          detail.descriptions.length > 0
            ? detail.descriptions[detail.descriptions.length - 1].body
            : "";
        setDraft({ name: detail.name, description: latestBody });
        setDescriptions(detail.descriptions);
        setEditorMode("edit");
      } catch (err) {
        console.error(`❌ Failed to load ${entityLabel}`, err);
        setError(`Could not load ${entityLabel}.`);
      }
    },
    [api, entityLabel],
  );

  const handleNew = useCallback(() => {
    setSelectedId(null);
    setDraft(EMPTY_DRAFT);
    setDescriptions([]);
    setOriginalName("");
    setEditorMode("create");
  }, []);

  const handleSave = useCallback(async () => {
    if (!draft.name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      if (editorMode === "create") {
        const created = await api.create(
          draft.name.trim(),
          draft.description.trim(),
        );
        setEntities((prev) => [
          ...prev,
          {
            id: created.id,
            name: created.name,
            description:
              created.descriptions.length > 0
                ? created.descriptions[created.descriptions.length - 1].body
                : null,
            description_version:
              created.descriptions.length > 0
                ? created.descriptions[created.descriptions.length - 1].version
                : null,
            created_at: created.created_at,
          },
        ]);
        setSelectedId(created.id);
        setOriginalName(created.name);
        setDescriptions(created.descriptions);
        setEditorMode("edit");
      } else if (editorMode === "edit" && selectedId !== null) {
        const nameChanged = draft.name.trim() !== originalName;
        const latestBody =
          descriptions.length > 0
            ? descriptions[descriptions.length - 1].body
            : "";
        const descChanged = draft.description.trim() !== latestBody;

        let updated: EntityDetailResponse | null = null;

        if (nameChanged) {
          updated = await api.updateName(selectedId, draft.name.trim());
        }
        if (descChanged && draft.description.trim()) {
          updated = await api.addDescription(
            selectedId,
            draft.description.trim(),
          );
        }

        if (updated) {
          setOriginalName(updated.name);
          setDescriptions(updated.descriptions);
          const latestDesc =
            updated.descriptions.length > 0
              ? updated.descriptions[updated.descriptions.length - 1]
              : null;
          setEntities((prev) =>
            prev.map((e) =>
              e.id === selectedId
                ? {
                    ...e,
                    name: updated.name,
                    description: latestDesc?.body ?? null,
                    description_version: latestDesc?.version ?? null,
                  }
                : e,
            ),
          );
        }
      }
    } catch (err) {
      console.error(`❌ Failed to save ${entityLabel}`, err);
      setError(`Could not save ${entityLabel}.`);
    } finally {
      setSaving(false);
    }
  }, [
    editorMode,
    selectedId,
    draft,
    originalName,
    descriptions,
    api,
    entityLabel,
  ]);

  const handleDelete = useCallback(async () => {
    if (selectedId === null) return;
    if (!confirm(`Delete this ${entityLabel}?`)) return;
    setError(null);
    try {
      await api.remove(selectedId);
      setEntities((prev) => prev.filter((e) => e.id !== selectedId));
      resetEditor();
    } catch (err) {
      console.error(`❌ Failed to delete ${entityLabel}`, err);
      setError(`Could not delete ${entityLabel}.`);
    }
  }, [selectedId, api, entityLabel, resetEditor]);

  if (loading) {
    return (
      <div className="entity-page">
        <p className="entity-loading">Loading {entityLabel}s...</p>
      </div>
    );
  }

  const nameChanged =
    editorMode === "edit" && draft.name.trim() !== originalName;
  const latestBody =
    descriptions.length > 0
      ? descriptions[descriptions.length - 1].body
      : "";
  const descChanged =
    editorMode === "edit" && draft.description.trim() !== latestBody;
  const hasChanges =
    editorMode === "create"
      ? draft.name.trim().length > 0
      : nameChanged || descChanged;

  return (
    <div className="entity-page">
      <div className="entity-container">
        {error && <div className="entity-error">{error}</div>}

        {/* ---- List ---- */}
        <div className="entity-section">
          <div className="entity-section-header">
            <h2 className="entity-section-title">{title}</h2>
            <div className="entity-section-actions">
              <button
                type="button"
                className="btn btn-sm btn-outline btn-primary"
                onClick={handleNew}
              >
                + New {entityLabel}
              </button>
            </div>
          </div>

          {entities.length > 0 ? (
            <div className="entity-list">
              {entities.map((entity) => (
                <button
                  key={entity.id}
                  type="button"
                  className={`entity-row ${selectedId === entity.id ? "selected" : ""}`}
                  onClick={() => handleSelect(entity.id)}
                >
                  <span className="entity-row-name">{entity.name}</span>
                  <span className="entity-row-badges">
                    {entity.description_version !== null && (
                      <span className="entity-row-badge">
                        v{entity.description_version}
                      </span>
                    )}
                    {entity.description === null && (
                      <span className="badge badge-warning badge-sm">
                        No description
                      </span>
                    )}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <p className="entity-empty">
              No {entityLabel}s yet. Create one to get started.
            </p>
          )}
        </div>

        {/* ---- Editor ---- */}
        {editorMode !== "idle" && (
          <div className="entity-section">
            <div className="entity-section-header">
              <h2 className="entity-section-title">
                {editorMode === "create"
                  ? `New ${entityLabel}`
                  : `Edit ${entityLabel}`}
              </h2>
            </div>

            <div className="entity-editor-form">
              <label className="entity-label">
                Name
                <input
                  type="text"
                  className="input input-sm w-full"
                  value={draft.name}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, name: e.target.value }))
                  }
                />
              </label>

              <label className="entity-label">
                Description
                {editorMode === "edit" && (
                  <span className="text-xs font-normal text-base-content/40">
                    Editing saves a new version
                  </span>
                )}
                <textarea
                  className="textarea textarea-sm w-full entity-textarea"
                  rows={12}
                  value={draft.description}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, description: e.target.value }))
                  }
                />
              </label>

              <div className="entity-editor-actions">
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  disabled={!hasChanges || !draft.name.trim() || saving}
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
                {editorMode === "edit" && selectedId !== null && (
                  <button
                    type="button"
                    className="btn btn-sm btn-error"
                    onClick={handleDelete}
                  >
                    Delete
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ---- Description History ---- */}
        {editorMode === "edit" && descriptions.length > 0 && (
          <div className="entity-section">
            <div className="entity-section-header">
              <h2 className="entity-section-title">Description History</h2>
            </div>
            <div className="entity-history">
              {[...descriptions].reverse().map((desc, idx) => (
                <div
                  key={desc.version}
                  className={`entity-history-item ${idx === 0 ? "active" : ""}`}
                >
                  <div className="entity-history-header">
                    <span>Version {desc.version}</span>
                    <span>
                      {new Date(desc.created_at).toLocaleDateString(undefined, {
                        year: "numeric",
                        month: "short",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </span>
                  </div>
                  <div className="entity-history-body">{desc.body}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default EntityManager;
