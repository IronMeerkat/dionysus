import { useCallback, useState } from "react";
import type { CharacterStatusEffect } from "../types/rest";
import { restService } from "../services/restService";
import StatusEffectModal from "./StatusEffectModal";
import "./CharacterStatusEffects.css";

interface CharacterStatusEffectsProps {
  characterId: number;
  effects: CharacterStatusEffect[];
  onChanged: () => Promise<void> | void;
}

const CharacterStatusEffects = ({
  characterId,
  effects,
  onChanged,
}: CharacterStatusEffectsProps) => {
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<CharacterStatusEffect | null>(null);

  const openCreate = useCallback(() => {
    setEditing(null);
    setModalOpen(true);
  }, []);

  const openEdit = useCallback((effect: CharacterStatusEffect) => {
    setEditing(effect);
    setModalOpen(true);
  }, []);

  const closeModal = useCallback(() => setModalOpen(false), []);

  const handleDelete = useCallback(
    async (effect: CharacterStatusEffect) => {
      if (!confirm(`Delete status effect '${effect.name}'?`)) return;
      try {
        await restService.deleteStatusEffect(characterId, effect.id);
        await onChanged();
      } catch (err) {
        console.error("❌ Failed to delete status effect", err);
        alert("Could not delete status effect.");
      }
    },
    [characterId, onChanged],
  );

  return (
    <div className="entity-section">
      <div className="entity-section-header">
        <h2 className="entity-section-title">Permanent Status Effects</h2>
        <div className="entity-section-actions">
          <button
            type="button"
            className="btn btn-sm btn-outline btn-primary"
            onClick={openCreate}
          >
            + Add Effect
          </button>
        </div>
      </div>

      {effects.length > 0 ? (
        <div className="status-effect-list">
          {effects.map((effect) => (
            <div key={effect.id} className="status-effect-card">
              <div className="status-effect-card-main">
                <div className="status-effect-card-header">
                  <span className="status-effect-name">{effect.name}</span>
                  <span className="status-effect-badges">
                    {effect.roll_modifier !== 0 && (
                      <span
                        className={`badge badge-sm ${
                          effect.roll_modifier > 0 ? "badge-success" : "badge-error"
                        }`}
                      >
                        {effect.roll_modifier > 0
                          ? `+${effect.roll_modifier}`
                          : effect.roll_modifier}
                      </span>
                    )}
                    {effect.advantage !== "normal" && (
                      <span
                        className={`badge badge-sm ${
                          effect.advantage === "advantage"
                            ? "badge-success"
                            : "badge-warning"
                        }`}
                      >
                        {effect.advantage}
                      </span>
                    )}
                  </span>
                </div>
                {effect.affects && (
                  <p className="status-effect-affects">Affects: {effect.affects}</p>
                )}
                {effect.description && (
                  <p className="status-effect-description">{effect.description}</p>
                )}
                {(effect.negated_by.length > 0 || effect.negation_condition) && (
                  <div className="status-effect-negation">
                    {effect.negated_by.map((name) => (
                      <span key={name} className="badge badge-sm badge-outline">
                        negated by {name}
                      </span>
                    ))}
                    {effect.negation_condition && (
                      <span className="badge badge-sm badge-outline">
                        negated when {effect.negation_condition}
                      </span>
                    )}
                  </div>
                )}
              </div>
              <div className="status-effect-card-actions">
                <button
                  type="button"
                  className="btn btn-xs btn-outline"
                  onClick={() => openEdit(effect)}
                >
                  Edit
                </button>
                <button
                  type="button"
                  className="btn btn-xs btn-outline btn-error"
                  onClick={() => handleDelete(effect)}
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="entity-empty">No permanent status effects on this sheet.</p>
      )}

      <StatusEffectModal
        open={modalOpen}
        onClose={closeModal}
        characterId={characterId}
        effect={editing}
        onSaved={onChanged}
      />
    </div>
  );
};

export default CharacterStatusEffects;
