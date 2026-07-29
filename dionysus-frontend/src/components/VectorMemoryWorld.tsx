import { useCallback, useEffect, useState } from "react";
import type {
  VectorMemoryApi,
  LoreEntryListItem,
  LoreEntryResponse,
} from "../types/rest";
import VectorMemoryEntryCard from "./VectorMemoryEntryCard";
import VectorMemoryEntryModal from "./VectorMemoryEntryModal";

interface VectorMemoryWorldProps {
  api: VectorMemoryApi;
}

const VectorMemoryWorld = ({ api }: VectorMemoryWorldProps) => {
  const [entries, setEntries] = useState<LoreEntryListItem[]>([]);
  const [selectedEntryId, setSelectedEntryId] = useState<number | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<"create" | "edit">("create");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEntries([]);
    setSelectedEntryId(null);
    setError(null);

    api
      .getEntries()
      .then(setEntries)
      .catch((err) => {
        console.error("❌ Failed to fetch entries:", err);
        setError("Could not load entries.");
      });
  }, [api]);

  const openCreateModal = useCallback(() => {
    setSelectedEntryId(null);
    setModalMode("create");
    setModalOpen(true);
  }, []);

  const openEditModal = useCallback((id: number) => {
    setSelectedEntryId(id);
    setModalMode("edit");
    setModalOpen(true);
  }, []);

  const closeModal = useCallback(() => {
    setModalOpen(false);
    setSelectedEntryId(null);
  }, []);

  const handleEntrySaved = useCallback((entry: LoreEntryResponse) => {
    setEntries((prev) => {
      const item = {
        id: entry.id,
        title: entry.title,
        created_at: entry.created_at,
        updated_at: entry.updated_at,
      };
      const exists = prev.some((e) => e.id === entry.id);
      if (exists) {
        return prev.map((e) => (e.id === entry.id ? item : e));
      }
      return [...prev, item];
    });
  }, []);

  const handleEntryDeleted = useCallback((id: number) => {
    setEntries((prev) => prev.filter((e) => e.id !== id));
    setSelectedEntryId(null);
  }, []);

  return (
    <>
      {error && <div className="lore-error">{error}</div>}

      <div className="lore-section">
        <div className="lore-section-header">
          <h2 className="lore-section-title">Entries</h2>
          <button
            type="button"
            className="btn btn-sm btn-outline btn-primary"
            onClick={openCreateModal}
          >
            + New Entry
          </button>
        </div>

        {entries.length > 0 ? (
          <div className="lore-entries-list">
            {entries.map((entry) => (
              <VectorMemoryEntryCard
                key={entry.id}
                entry={entry}
                selected={selectedEntryId === entry.id}
                onClick={() => openEditModal(entry.id)}
              />
            ))}
          </div>
        ) : (
          <p className="lore-empty">No entries yet.</p>
        )}
      </div>

      <VectorMemoryEntryModal
        open={modalOpen}
        onClose={closeModal}
        mode={modalMode}
        entryId={selectedEntryId}
        api={api}
        onSaved={handleEntrySaved}
        onDeleted={handleEntryDeleted}
      />
    </>
  );
};

export default VectorMemoryWorld;
