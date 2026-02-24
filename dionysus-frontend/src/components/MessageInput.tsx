import { useCallback, useRef, useState } from "react";
import "./MessageInput.css";

interface MessageInputProps {
  onSend: (text: string) => void;
}

const MessageInput = ({ onSend }: MessageInputProps) => {
  const [message, setMessage] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const resetHeight = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setMessage(e.target.value);
    resetHeight();
  };

  const handleSend = useCallback(() => {
    const trimmed = message.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setMessage("");
    requestAnimationFrame(() => resetHeight());
  }, [message, resetHeight, onSend]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.shiftKey && e.key === "Enter") {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="message-input-bar">
      <div className="message-input-inner">
        <textarea
          ref={textareaRef}
          className="message-input-textarea textarea textarea-bordered"
          rows={1}
          placeholder="Send a message…"
          aria-label="Chat message input"
          value={message}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
        />
        <button
          type="button"
          className="message-input-send btn btn-primary"
          disabled={!message.trim()}
          onClick={handleSend}
        >
          Send
        </button>
      </div>
    </div>
  );
};

export default MessageInput;
