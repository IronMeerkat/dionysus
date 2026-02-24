import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./LocationModal.css";

const API_BASE = import.meta.env.VITE_API_URL ?? `http://${window.location.hostname}:8000`;

interface LocationModalProps {
  open: boolean;
  onClose: () => void;
}

const LocationModal = ({ open, onClose }: LocationModalProps) => {
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

    fetch(`${API_BASE}/location`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: { location: string } = await res.json();
        if (!cancelled) setValue(data.location);
      })
      .catch((err) => {
        console.error("❌ Failed to load location:", err);
        if (!cancelled) setFeedback("Could not load current location.");
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
      const res = await fetch(`${API_BASE}/location`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ location: trimmed }),
      });

      if (!res.ok) {
        const err = await res.text();
        console.error("❌ Location update failed:", err);
        setFeedback("Failed to update location.");
        return;
      }

      setFeedback("Location updated!");
      setTimeout(closeModal, 800);
    } catch (err) {
      console.error("❌ Location request error:", err);
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
      className="location-modal"
      onClose={closeModal}
    >
      <div className="location-modal-box">
        <h3 className="location-modal-title">Location</h3>

        <input
          type="text"
          className="location-modal-input input input-bordered"
          placeholder={loading ? "Loading..." : "Enter location..."}
          disabled={loading}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") handleSubmit(); }}
        />

        {feedback && (
          <p className="location-modal-feedback">{feedback}</p>
        )}

        <div className="location-modal-actions">
          <button
            type="button"
            className="location-modal-cancel btn btn-sm btn-primary"
            onClick={closeModal}
          >
            Cancel
          </button>
          <button
            type="button"
            className="location-modal-submit btn btn-sm btn-primary"
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

export default LocationModal;
