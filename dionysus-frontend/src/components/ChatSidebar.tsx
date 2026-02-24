import { useCallback, useEffect } from "react";
import { useConversationStore } from "../contexts/ConversationStore";
import { useSessionStore } from "../contexts/SessionStore";
import { useMessageStore } from "../contexts/MessageStore";
import { restService } from "../services/restService";
import "./ChatSidebar.css";

interface ChatSidebarProps {
  playerName?: string;
  characterNames?: string[];
  mobileOpen?: boolean;
  onClose?: () => void;
  onAfterSelect?: () => void;
}

const ChatSidebar = ({ playerName, characterNames, mobileOpen, onClose, onAfterSelect }: ChatSidebarProps) => {
  const { conversations, loading, fetchConversations, setActiveConversation } = useConversationStore();
  const { setPlayer, setCharacters } = useSessionStore();
  const setMessages = useMessageStore((s) => s.setMessages);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  const handleSelectConversation = useCallback(async (conversationId: number) => {
    try {
      const res = await restService.loadConversation(conversationId);
      setActiveConversation(conversationId, res.title);
      setPlayer(res.player);
      setCharacters(res.characters);
      setMessages(
        res.messages.map((m) => ({
          id: m.id,
          content: m.content,
          role: m.role,
          name: m.name,
          createdAt: new Date(m.created_at),
        })),
      );
      onAfterSelect?.();
    } catch (err) {
      console.error("🔥 Failed to load conversation", err);
    }
  }, [setActiveConversation, setPlayer, setCharacters, setMessages, onAfterSelect]);

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

        <hr className="chat-sidebar-divider" />

        <div className="chat-sidebar-section chat-sidebar-conversations">
          <span className="chat-sidebar-label">Conversations</span>

          {loading && <span className="chat-sidebar-loading">Loading…</span>}

          {!loading && conversations.length === 0 && (
            <span className="chat-sidebar-empty">No conversations yet</span>
          )}

          {!loading && conversations.length > 0 && (
            <ul className="chat-sidebar-conversation-list">
              {conversations.map((conv) => (
                <li key={conv.id}>
                  <button
                    type="button"
                    className="chat-sidebar-conversation-item"
                    onClick={() => handleSelectConversation(conv.id)}
                  >
                    {conv.title ?? `Conversation #${conv.id}`}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </aside>
    </>
  );
};

export default ChatSidebar;
