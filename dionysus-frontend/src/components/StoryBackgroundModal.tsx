import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./StoryBackgroundModal.css";

const API_BASE = import.meta.env.VITE_API_URL ?? `http://${window.location.hostname}:8000`;

interface StoryBackgroundModalProps {
  open: boolean;
  onClose: () => void;
}

const StoryBackgroundModal = ({ open, onClose }: StoryBackgroundModalProps) => {
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (!open) return;

    let cancelled = false;
    setLoading(true);
    setFeedback(null);

    fetch(`${API_BASE}/story_background`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: { story_background: string } = await res.json();
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
  }, [open]);

  const closeModal = useCallback(() => {
    dialogRef.current?.close();
    onClose();
  }, [onClose]);

  const handleSubmit = useCallback(async () => {
    const trimmed = value.trim();
    if (!trimmed) return;

    setSubmitting(true);
    setFeedback(null);

    try {
      const res = await fetch(`${API_BASE}/story_background`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ story_background: trimmed }),
      });

      if (!res.ok) {
        const err = await res.text();
        console.error("❌ Story background update failed:", err);
        setFeedback("Failed to update story background.");
        return;
      }

      setFeedback("Story background updated!");
      setTimeout(closeModal, 800);
    } catch (err) {
      console.error("❌ Story background request error:", err);
      setFeedback("Could not reach the server.");
    } finally {
      setSubmitting(false);
    }
  }, [value, closeModal]);

  if (!open) return null;

  return createPortal(
    <dialog
      ref={(node) => {
        (dialogRef as React.MutableRefObject<HTMLDialogElement | null>).current = node;
        if (node && !node.open) node.showModal();
      }}
      className="story-modal"
      onClose={closeModal}
    >
      <div className="story-modal-box">
        <h3 className="story-modal-title">Story Background</h3>

        <textarea
          className="story-modal-textarea textarea textarea-bordered"
          rows={6}
          placeholder={loading ? "Loading..." : "Describe the story background..."}
          disabled={loading}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />

        {feedback && (
          <p className="story-modal-feedback">{feedback}</p>
        )}

        <div className="story-modal-actions">
          <button
            type="button"
            className="story-modal-cancel btn btn-sm btn-primary"
            onClick={closeModal}
          >
            Cancel
          </button>
          <button
            type="button"
            className="story-modal-submit btn btn-sm btn-primary"
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
