import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./VectorMemoryEntryModal.css";
import type { VectorMemoryApi, LoreEntryResponse } from "../types/rest";

interface VectorMemoryEntryModalProps {
  open: boolean;
  onClose: () => void;
  mode: "create" | "edit";
  entryUuid: string | null;
  api: VectorMemoryApi;
  onSaved: (entry: LoreEntryResponse) => void;
  onDeleted: (uuid: string) => void;
}

const VectorMemoryEntryModal = ({
  open,
  onClose,
  mode,
  entryUuid,
  api,
  onSaved,
  onDeleted,
}: VectorMemoryEntryModalProps) => {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [isEntity, setIsEntity] = useState(false);
  const [entityType, setEntityType] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (!open) return;

    setTitle("");
    setContent("");
    setFeedback(null);
    setIsEntity(false);
    setEntityType(null);

    if (mode === "edit" && entryUuid) {
      let cancelled = false;
      setLoading(true);

      api
        .getEntry(entryUuid)
        .then((full) => {
          if (!cancelled) {
            setTitle(full.title);
            setContent(full.content);
            setIsEntity(full.kind === "entity");
            setEntityType(full.entity_type ?? null);
          }
        })
        .catch((err) => {
          console.error("❌ Failed to load entry:", err);
          if (!cancelled) setFeedback("Could not load entry.");
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });

      return () => {
        cancelled = true;
      };
    }
  }, [open, mode, entryUuid, api]);

  const closeModal = useCallback(() => {
    dialogRef.current?.close();
    onClose();
  }, [onClose]);

  const handleSave = useCallback(async () => {
    const trimmedTitle = title.trim();
    const trimmedContent = content.trim();
    if (!trimmedTitle || !trimmedContent) return;

    setSubmitting(true);
    setFeedback(null);

    try {
      if (mode === "create") {
        const created = await api.createEntry(trimmedTitle, trimmedContent);
        onSaved(created);
      } else if (entryUuid) {
        const updated = await api.updateEntry(
          entryUuid,
          trimmedTitle,
          trimmedContent,
        );
        onSaved(updated);
      }
      closeModal();
    } catch (err) {
      console.error("❌ Failed to save entry:", err);
      setFeedback("Could not save entry.");
    } finally {
      setSubmitting(false);
    }
  }, [title, content, mode, entryUuid, api, onSaved, closeModal]);

  const handleDelete = useCallback(async () => {
    if (!entryUuid) return;
    if (!confirm("Delete this entry?")) return;

    setSubmitting(true);
    setFeedback(null);

    try {
      await api.deleteEntry(entryUuid);
      onDeleted(entryUuid);
      closeModal();
    } catch (err) {
      console.error("❌ Failed to delete entry:", err);
      setFeedback("Could not delete entry.");
    } finally {
      setSubmitting(false);
    }
  }, [entryUuid, api, onDeleted, closeModal]);

  if (!open) return null;

  return createPortal(
    <dialog
      ref={(node) => {
        (dialogRef as React.MutableRefObject<HTMLDialogElement | null>).current =
          node;
        if (node && !node.open) node.showModal();
      }}
      className="modal-dialog"
      onClose={closeModal}
    >
      <div className="modal-body">
        <h3 className="modal-title">
          {isEntity
            ? `Edit ${entityType ?? "Entity"}`
            : mode === "create"
              ? "New Entry"
              : "Edit Entry"}
        </h3>

        <input
          type="text"
          className="vm-modal-input input input-sm input-bordered"
          placeholder={loading ? "Loading..." : "Title"}
          disabled={loading}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />

        <textarea
          className="vm-modal-textarea textarea textarea-bordered"
          rows={10}
          placeholder={loading ? "Loading..." : "Content"}
          disabled={loading}
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />

        {feedback && <p className="modal-feedback">{feedback}</p>}

        <div className="modal-actions">
          {mode === "edit" && entryUuid && (
            <button
              type="button"
              className="btn btn-sm btn-error mr-auto"
              disabled={submitting}
              onClick={handleDelete}
            >
              Delete
            </button>
          )}
          <button
            type="button"
            className="btn-action btn btn-sm btn-primary"
            onClick={closeModal}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn-action btn btn-sm btn-primary"
            disabled={
              !title.trim() || !content.trim() || submitting || loading
            }
            onClick={handleSave}
          >
            {submitting ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </dialog>,
    document.body,
  );
};

export default VectorMemoryEntryModal;
