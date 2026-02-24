interface PlayerSelectProps {
  items: PlayerOption[];
  selectedId: number | null;
  onChange: (id: number | null) => void;
}

const PlayerSelect = ({ items, selectedId, onChange }: PlayerSelectProps) => {
  return (
    <div className="session-setup-section">
      <label className="session-setup-label" htmlFor="player-select">
        Player
      </label>
      <select
        id="player-select"
        className="session-setup-select select select-bordered"
        value={selectedId ?? ""}
        onChange={(e) =>
          onChange(e.target.value ? Number(e.target.value) : null)
        }
      >
        <option value="" disabled>
          Choose a player...
        </option>
        {items.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
      </select>
    </div>
  );
};

export default PlayerSelect;
