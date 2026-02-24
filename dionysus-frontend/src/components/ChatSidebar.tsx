import "./ChatSidebar.css";

interface ChatSidebarProps {
  playerName?: string;
  characterNames?: string[];
  mobileOpen?: boolean;
  onClose?: () => void;
}

const ChatSidebar = ({ playerName, characterNames, mobileOpen, onClose }: ChatSidebarProps) => {
  return (
    <>
      {mobileOpen && (
        <div
          className="chat-sidebar-backdrop"
          onClick={onClose}
          onKeyDown={(e) => { if (e.key === "Escape" && onClose) onClose(); }}
          role="button"
          tabIndex={-1}
          aria-label="Close sidebar"
        />
      )}

      <aside className={`chat-sidebar ${mobileOpen ? "chat-sidebar--open" : ""}`}>
        <div className="chat-sidebar-header">
          <h2 className="chat-sidebar-title">Session</h2>
          {onClose && (
            <button
              type="button"
              className="chat-sidebar-close"
              aria-label="Close sidebar"
              onClick={onClose}
            >
              ✕
            </button>
          )}
        </div>

        {playerName && (
          <div className="chat-sidebar-section">
            <span className="chat-sidebar-label">Player</span>
            <span className="chat-sidebar-value">{playerName}</span>
          </div>
        )}

        {characterNames && characterNames.length > 0 && (
          <div className="chat-sidebar-section">
            <span className="chat-sidebar-label">Characters</span>
            <ul className="chat-sidebar-character-list">
              {characterNames.map((name) => (
                <li key={name} className="chat-sidebar-character-item">
                  {name}
                </li>
              ))}
            </ul>
          </div>
        )}
      </aside>
    </>
  );
};

export default ChatSidebar;
