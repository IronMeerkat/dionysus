import { useCallback, useEffect, useRef, useState } from "react";
import "./TextMessage.css";
import { restService } from "../services/restService";
import { useMessageStore } from "../contexts/MessageStore";

interface TextMessageProps {
  message: Message;
}

function formatTime(date: Date): string {
  return new Date(date).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function AvatarPlaceholder({ name }: { name: string }) {
  const initials = name
    .split(" ")
    .map((word) => word[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  return (
    <div className="avatar-placeholder">
      {initials}
    </div>
  );
}

const TextMessage = ({ message }: TextMessageProps) => {
  const isUser = message.role === "user";
  const alignment = isUser ? "chat-sender" : "chat-receiver";
  const updateMessageContent = useMessageStore((s) => s.updateMessageContent);
  const removeMessage = useMessageStore((s) => s.removeMessage);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState(message.content);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const editMessage = useCallback(async () => {
    await restService.editMessage(message.id, editContent);
    updateMessageContent(message.id, editContent);
    setEditing(false);
  }, [message.id, editContent, updateMessageContent]);

  const resizeTextarea = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.width = "100%";
    ta.style.height = `${ta.scrollHeight}px`;
  }, []);

  const startEditing = useCallback(() => {
    setEditContent(message.content);
    setEditing(true);
  }, [message.content]);

  const cancelEditing = useCallback(() => {
    setEditing(false);
  }, []);

  const deleteMessage = useCallback(async () => {
    await restService.deleteMessage(message.id);
    removeMessage(message.id);
  }, [message.id, removeMessage]);

  useEffect(() => {
    if (editing) {
      resizeTextarea();
      textareaRef.current?.focus();
      textareaRef.current?.select();
    }
  }, [editing, resizeTextarea]);

  return (
    <div className={`chat ${alignment}`}>
      <div className="chat-avatar avatar">
        <AvatarPlaceholder name={message.name} />
      </div>

      <div className="chat-header text-message-header">
        {message.name} 
        <time className="text-message-time"> {formatTime(message.createdAt)}</time>
      </div>

      <div className={`chat-bubble ${editing ? "chat-bubble-editing" : ""}`} onDoubleClick={startEditing}>
        {editing ? 
        (<form onSubmit={(e) => { e.preventDefault(); editMessage(); }}>
        <textarea
          ref={textareaRef}
          value={editContent}
          onChange={(e) => { setEditContent(e.target.value); requestAnimationFrame(resizeTextarea); }}
          onBlur={(e) => {
            if (e.relatedTarget && e.currentTarget.form?.contains(e.relatedTarget)) return;
            cancelEditing();
          }}
        />
        <button type="submit" className="chat-title-save">Save</button>
        <button type="button" className="chat-title-delete" onClick={deleteMessage}>Delete</button>
        
        </form>) : (<div className="chat-bubble-content" style={{ whiteSpace: "pre-wrap" }}>{message.content}</div>)}
      </div>
    </div>
  );
};

export default TextMessage;
