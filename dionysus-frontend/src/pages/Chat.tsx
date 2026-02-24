import { useCallback, useEffect, useRef, useState } from "react";
import ChatSidebar from "../components/ChatSidebar";
import MessageInput from "../components/MessageInput";
import SessionSetup from "../components/SessionSetup";
import TextMessage from "../components/TextMessage";
import { useSocket } from "../hooks/useSocket";
import type {
  StreamStartPayload,
  StreamTokenPayload,
  StreamEndPayload,
} from "../types/socket";
import "./Chat.css";

function generateId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}

const CONVERSATION_ID = "default";

interface SessionInfo {
  player: PlayerOption;
  characters: CharacterOption[];
}

interface ChatProps {
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
}

const Chat = ({ sidebarOpen, onToggleSidebar }: ChatProps) => {
  const { socket } = useSocket();
  const [messages, setMessages] = useState<Message[]>([]);
  const [session, setSession] = useState<SessionInfo | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const closeSidebar = useCallback(() => {
    if (sidebarOpen) onToggleSidebar();
  }, [sidebarOpen, onToggleSidebar]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const handleStreamStart = ({ messageId, name }: StreamStartPayload) => {
      const botMsg: Message = {
        id: messageId,
        content: "",
        role: "assistant",
        name,
        createdAt: new Date(),
        streaming: true,
      };
      setMessages((prev) => [...prev, botMsg]);
    };

    const handleStreamToken = ({ messageId, token }: StreamTokenPayload) => {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === messageId ? { ...m, content: m.content + token } : m,
        ),
      );
    };

    const handleStreamEnd = ({ messageId }: StreamEndPayload) => {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === messageId ? { ...m, streaming: false } : m,
        ),
      );
    };

    socket.on("stream_start", handleStreamStart);
    socket.on("stream_token", handleStreamToken);
    socket.on("stream_end", handleStreamEnd);

    return () => {
      socket.off("stream_start", handleStreamStart);
      socket.off("stream_token", handleStreamToken);
      socket.off("stream_end", handleStreamEnd);
    };
  }, [socket]);

  const handleSend = useCallback(
    (text: string) => {
      const userMsg: Message = {
        id: generateId(),
        content: text,
        role: "user",
        name: session?.player.name ?? "You",
        createdAt: new Date(),
      };

      setMessages((prev) => [...prev, userMsg]);
      socket.sendMessage(CONVERSATION_ID, text);
    },
    [socket, session],
  );

  const handleSessionReady = useCallback(
    (player: PlayerOption, characters: CharacterOption[]) => {
      setSession({ player, characters });
    },
    [],
  );

  if (!session) {
    return (
      <div className="chat-layout">
        <ChatSidebar mobileOpen={sidebarOpen} onClose={closeSidebar} />
        <SessionSetup onReady={handleSessionReady} />
      </div>
    );
  }

  return (
    <div className="chat-layout">
      <ChatSidebar
        playerName={session.player.name}
        characterNames={session.characters.map((c) => c.name)}
        mobileOpen={sidebarOpen}
        onClose={closeSidebar}
      />

      <main className="chat-main">
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
