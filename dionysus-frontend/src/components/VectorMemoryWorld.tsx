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
  const [selectedEntryUuid, setSelectedEntryUuid] = useState<string | null>(
    null,
  );
  const [modalOpen, setModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<"create" | "edit">("create");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEntries([]);
    setSelectedEntryUuid(null);
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
    setSelectedEntryUuid(null);
    setModalMode("create");
    setModalOpen(true);
  }, []);

  const openEditModal = useCallback((uuid: string) => {
    setSelectedEntryUuid(uuid);
    setModalMode("edit");
    setModalOpen(true);
  }, []);

  const closeModal = useCallback(() => {
    setModalOpen(false);
    setSelectedEntryUuid(null);
  }, []);

  const handleEntrySaved = useCallback((entry: LoreEntryResponse) => {
    setEntries((prev) => {
      const item = {
        uuid: entry.uuid,
        title: entry.title,
        created_at: entry.created_at,
        kind: entry.kind,
        entity_type: entry.entity_type,
      };
      const exists = prev.some((e) => e.uuid === entry.uuid);
      if (exists) {
        return prev.map((e) => (e.uuid === entry.uuid ? item : e));
      }
      return [...prev, item];
    });
  }, []);

  const handleEntryDeleted = useCallback((uuid: string) => {
    setEntries((prev) => prev.filter((e) => e.uuid !== uuid));
    setSelectedEntryUuid(null);
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
                key={entry.uuid}
                entry={entry}
                selected={selectedEntryUuid === entry.uuid}
                onClick={() => openEditModal(entry.uuid)}
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
        entryUuid={selectedEntryUuid}
        api={api}
        onSaved={handleEntrySaved}
        onDeleted={handleEntryDeleted}
      />
    </>
  );
};

export default VectorMemoryWorld;
