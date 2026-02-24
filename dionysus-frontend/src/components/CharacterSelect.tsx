interface CharacterSelectProps {
  items: CharacterOption[];
  selectedIds: Set<number>;
  onToggle: (id: number) => void;
}

const CharacterSelect = ({ items, selectedIds, onToggle }: CharacterSelectProps) => {
  return (
    <div className="session-setup-section">
      <span className="session-setup-label">Characters</span>
      <div className="session-setup-characters">
        {items.map((item) => (
          <label
            key={item.id}
            className={`session-setup-character-item ${
              selectedIds.has(item.id) ? "selected" : ""
            }`}
          >
            <input
              type="checkbox"
              className="session-setup-character-check"
              checked={selectedIds.has(item.id)}
              onChange={() => onToggle(item.id)}
            />
            <span className="session-setup-character-name">{item.name}</span>
          </label>
        ))}
      </div>
    </div>
  );
};

export default CharacterSelect;
