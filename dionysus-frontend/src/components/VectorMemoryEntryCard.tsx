import type { LoreEntryListItem } from "../types/rest";

interface VectorMemoryEntryCardProps {
  entry: LoreEntryListItem;
  selected: boolean;
  onClick: () => void;
}

const VectorMemoryEntryCard = ({
  entry,
  selected,
  onClick,
}: VectorMemoryEntryCardProps) => (
  <button
    type="button"
    className={`lore-entry-row ${selected ? "selected" : ""}`}
    onClick={onClick}
  >
    <span className="lore-entry-title">{entry.title}</span>
  </button>
);

export default VectorMemoryEntryCard;
