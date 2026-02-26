import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./StoryBackgroundModal.css";
import { restService } from "../services/restService";
import { useConversationStore } from "../contexts/ConversationStore";

interface StoryBackgroundModalProps {
  open: boolean;
  onClose: () => void;
}

const StoryBackgroundModal = ({ open, onClose }: StoryBackgroundModalProps) => {
  const activeConversationId = useConversationStore((s) => s.activeConversationId);
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (!open || activeConversationId === null) return;

    let cancelled = false;
    setLoading(true);
    setFeedback(null);

    restService.getStoryBackground(activeConversationId)
      .then((data) => {
        if (!cancelled) setValue(data.story_background);
      })
      .catch((err) => {
        console.error("❌ Failed to load story background:", err);
        if (!cancelled) setFeedback("Could not load current story background.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [open, activeConversationId]);

  const closeModal = useCallback(() => {
    dialogRef.current?.close();
    onClose();
  }, [onClose]);

  const handleSubmit = useCallback(async () => {
    const trimmed = value.trim();
    if (!trimmed || activeConversationId === null) return;

    setSubmitting(true);
    setFeedback(null);

    try {
      await restService.updateStoryBackground(activeConversationId, trimmed);
      setFeedback("Story background updated!");
      setTimeout(closeModal, 800);
    } catch (err) {
      console.error("❌ Story background update failed:", err);
      setFeedback("Failed to update story background.");
    } finally {
      setSubmitting(false);
    }
  }, [value, closeModal, activeConversationId]);

  if (!open) return null;

  return createPortal(
    <dialog
      ref={(node) => {
        (dialogRef as React.MutableRefObject<HTMLDialogElement | null>).current = node;
        if (node && !node.open) node.showModal();
      }}
      className="modal-dialog"
      onClose={closeModal}
    >
      <div className="modal-body">
        <h3 className="modal-title">Story Background</h3>

        <textarea
          className="story-modal-textarea textarea textarea-bordered"
          rows={6}
          placeholder={loading ? "Loading..." : "Describe the story background..."}
          disabled={loading}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />

        {feedback && (
          <p className="modal-feedback">{feedback}</p>
        )}

        <div className="modal-actions">
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
            disabled={!value.trim() || submitting}
            onClick={handleSubmit}
          >
            {submitting ? "Saving..." : "Save"}
          </button>
        </div>
      </div>

    </dialog>,
    document.body,
  );
};

export default StoryBackgroundModal;
