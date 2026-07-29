import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type {
  AdvantageState,
  CharacterStatusEffect,
  StatusEffectPayload,
} from "../types/rest";
import { restService } from "../services/restService";
import "./StatusEffectModal.css";

interface StatusEffectModalProps {
  open: boolean;
  onClose: () => void;
  characterId: number;
  effect: CharacterStatusEffect | null;
  onSaved: () => Promise<void> | void;
}

const ADVANTAGE_OPTIONS: AdvantageState[] = ["normal", "advantage", "disadvantage"];

const StatusEffectModal = ({
  open,
  onClose,
  characterId,
  effect,
  onSaved,
}: StatusEffectModalProps) => {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [affects, setAffects] = useState("");
  const [rollModifier, setRollModifier] = useState(0);
  const [advantage, setAdvantage] = useState<AdvantageState>("normal");
  const [negatedBy, setNegatedBy] = useState("");
  const [negationCondition, setNegationCondition] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (!open) return;
    setName(effect?.name ?? "");
    setDescription(effect?.description ?? "");
    setAffects(effect?.affects ?? "");
    setRollModifier(effect?.roll_modifier ?? 0);
    setAdvantage(effect?.advantage ?? "normal");
    setNegatedBy((effect?.negated_by ?? []).join(", "));
    setNegationCondition(effect?.negation_condition ?? "");
    setFeedback(null);
  }, [open, effect]);

  const closeModal = useCallback(() => {
    dialogRef.current?.close();
    onClose();
  }, [onClose]);

  const handleSave = useCallback(async () => {
    const payload: StatusEffectPayload = {
      name: name.trim(),
      description: description.trim(),
      affects: affects.trim(),
      roll_modifier: rollModifier,
      advantage,
      negated_by: negatedBy
        .split(",")
        .map((n) => n.trim())
        .filter(Boolean),
      negation_condition: negationCondition.trim() || null,
    };
    if (!payload.name) return;

    setSubmitting(true);
    setFeedback(null);
    try {
      if (effect) {
        await restService.updateStatusEffect(characterId, effect.id, payload);
      } else {
        await restService.createStatusEffect(characterId, payload);
      }
      await onSaved();
      closeModal();
    } catch (err) {
      console.error("❌ Failed to save status effect:", err);
      setFeedback("Could not save status effect (name must be unique per character).");
    } finally {
      setSubmitting(false);
    }
  }, [
    name,
    description,
    affects,
    rollModifier,
    advantage,
    negatedBy,
    negationCondition,
    effect,
    characterId,
    onSaved,
    closeModal,
  ]);

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
      <div className="modal-body status-effect-modal-body">
        <h3 className="modal-title">
          {effect ? "Edit Status Effect" : "New Status Effect"}
        </h3>

        <label className="se-field">
          <span>Name</span>
          <input
            type="text"
            className="input input-sm input-bordered w-full"
            placeholder="e.g. Autism"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>

        <label className="se-field">
          <span>Description</span>
          <textarea
            className="textarea textarea-sm textarea-bordered w-full"
            rows={2}
            placeholder="What this trait means for the character"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>

        <label className="se-field">
          <span>Affects</span>
          <input
            type="text"
            className="input input-sm input-bordered w-full"
            placeholder="Which rolls it modifies, e.g. social gambits"
            value={affects}
            onChange={(e) => setAffects(e.target.value)}
          />
        </label>

        <div className="se-field-row">
          <label className="se-field">
            <span>Roll modifier</span>
            <input
              type="number"
              className="input input-sm input-bordered w-full"
              value={rollModifier}
              onChange={(e) => setRollModifier(Number(e.target.value) || 0)}
            />
          </label>
          <label className="se-field">
            <span>Advantage</span>
            <select
              className="select select-sm select-bordered w-full"
              value={advantage}
              onChange={(e) => setAdvantage(e.target.value as AdvantageState)}
            >
              {ADVANTAGE_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="se-field">
          <span>Negated by (comma-separated character names)</span>
          <input
            type="text"
            className="input input-sm input-bordered w-full"
            placeholder="e.g. Reiko"
            value={negatedBy}
            onChange={(e) => setNegatedBy(e.target.value)}
          />
        </label>

        <label className="se-field">
          <span>Negation condition (optional)</span>
          <input
            type="text"
            className="input input-sm input-bordered w-full"
            placeholder="e.g. when she wears her headphones"
            value={negationCondition}
            onChange={(e) => setNegationCondition(e.target.value)}
          />
        </label>

        {feedback && <p className="modal-feedback">{feedback}</p>}

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
            disabled={!name.trim() || submitting}
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

export default StatusEffectModal;
