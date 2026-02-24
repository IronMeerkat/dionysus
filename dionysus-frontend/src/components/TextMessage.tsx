import "./TextMessage.css";

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

  return (
    <div className={`chat ${alignment}`}>
      <div className="chat-avatar avatar">
        <AvatarPlaceholder name={message.name} />
      </div>

      <div className="chat-header text-message-header">
        {message.name} 
        <time className="text-message-time"> {formatTime(message.createdAt)}</time>
      </div>

      <div className="chat-bubble">{message.content}</div>
    </div>
  );
};

export default TextMessage;
