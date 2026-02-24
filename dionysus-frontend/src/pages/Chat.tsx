import { useCallback, useEffect, useRef, useState } from "react";
import { Navigate } from "react-router";
import ChatSidebar from "../components/ChatSidebar";
import MessageInput from "../components/MessageInput";
import TextMessage from "../components/TextMessage";
import { useSocket } from "../hooks/useSocket";
import { useSessionStore } from "../contexts/SessionStore";
import { useConversationStore } from "../contexts/ConversationStore";
import { useMessageStore } from "../contexts/MessageStore";
import type {
  StreamStartPayload,
  StreamTokenPayload,
  StreamEndPayload,
} from "../types/socket";
import "./Chat.css";

interface ChatProps {
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
}

const Chat = ({ sidebarOpen, onToggleSidebar }: ChatProps) => {
  const { socket } = useSocket();
  const { messages, addUserMessage, startStream, appendToken, finalizeStream } = useMessageStore();
  const { player, characters } = useSessionStore();
  const activeConversationId = useConversationStore((s) => s.activeConversationId);
  const activeConversationTitle = useConversationStore((s) => s.activeConversationTitle);
  const renameConversation = useConversationStore((s) => s.renameConversation);
  const bottomRef = useRef<HTMLDivElement>(null);

  const [editingTitle, setEditingTitle] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const titleInputRef = useRef<HTMLInputElement>(null);

  const closeSidebar = useCallback(() => {
    if (sidebarOpen) onToggleSidebar();
  }, [sidebarOpen, onToggleSidebar]);

  const startEditingTitle = useCallback(() => {
    setDraftTitle(activeConversationTitle ?? "");
    setEditingTitle(true);
  }, [activeConversationTitle]);

  const saveTitle = useCallback(async () => {
    const trimmed = draftTitle.trim();
    if (trimmed && trimmed !== activeConversationTitle) {
      await renameConversation(trimmed);
    }
    setEditingTitle(false);
  }, [draftTitle, activeConversationTitle, renameConversation]);

  useEffect(() => {
    if (editingTitle) {
      titleInputRef.current?.focus();
      titleInputRef.current?.select();
    }
  }, [editingTitle]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const handleStreamStart = ({ messageId, name }: StreamStartPayload) => {
      startStream(messageId, name);
    };

    const handleStreamToken = ({ messageId, token }: StreamTokenPayload) => {
      appendToken(messageId, token);
    };

    const handleStreamEnd = ({ messageId }: StreamEndPayload) => {
      finalizeStream(messageId);
    };

    socket.on("stream_start", handleStreamStart);
    socket.on("stream_token", handleStreamToken);
    socket.on("stream_end", handleStreamEnd);

    return () => {
      socket.off("stream_start", handleStreamStart);
      socket.off("stream_token", handleStreamToken);
      socket.off("stream_end", handleStreamEnd);
    };
  }, [socket, startStream, appendToken, finalizeStream]);

  const handleSend = useCallback(
    (text: string) => {
      addUserMessage(text, player?.name ?? "You");
      socket.sendMessage(String(activeConversationId ?? ""), text);
    },
    [socket, player, addUserMessage, activeConversationId],
  );


  if (!player || characters.length === 0) {
    return <Navigate to="/session-setup" replace />;
  }

  return (
    <div className="page-layout">
      <ChatSidebar
        playerName={player.name}
        characterNames={characters.map((c) => c.name)}
        mobileOpen={sidebarOpen}
        onClose={closeSidebar}
      />

      <main className="chat-main">
        {activeConversationTitle && (
          <div className="chat-title-bar">
            {editingTitle ? (
              <form
                className="chat-title-edit"
                onSubmit={(e) => { e.preventDefault(); saveTitle(); }}
              >
                <input
                  ref={titleInputRef}
                  className="chat-title-input"
                  value={draftTitle}
                  onChange={(e) => setDraftTitle(e.target.value)}
                  onBlur={saveTitle}
                />
                <button type="submit" className="chat-title-save">
                  Save
                </button>
              </form>
            ) : (
              <h1
                className="chat-title"
                onDoubleClick={startEditingTitle}
                title="Double-click to rename"
              >
                {activeConversationTitle}
              </h1>
            )}
          </div>
        )}

        <div className="chat-messages-scroll">
          <div className="chat-messages-list">
            {messages.length === 0 && (
              <p className="chat-empty-state">
                Send a message to start chatting.
              </p>
            )}
            {messages.map((msg) => (
              <TextMessage key={msg.id} message={msg} />
            ))}
            <div ref={bottomRef} />
          </div>
        </div>

        <MessageInput onSend={handleSend} />
      </main>
    </div>
  );
};

export default Chat;
