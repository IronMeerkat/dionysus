import { create } from "zustand";

function generateId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

interface MessageStoreState {
  messages: Message[];
  setMessages: (messages: Message[]) => void;
  addUserMessage: (content: string, playerName: string) => void;
  updateMessageContent: (messageId: string, content: string) => void;
  removeMessage: (messageId: string) => void;
  startStream: (messageId: string, name: string) => void;
  appendToken: (messageId: string, token: string) => void;
  finalizeStream: (messageId: string) => void;
}

const useMessageStore = create<MessageStoreState>((set) => ({
  messages: [],

  setMessages: (messages) => set({ messages }),

  addUserMessage: (content, playerName) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: generateId(),
          content,
          role: "user",
          name: playerName,
          createdAt: new Date(),
        },
      ],
    })),

  updateMessageContent: (messageId, content) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === messageId ? { ...m, content } : m,
      ),
    })),

  removeMessage: (messageId) =>
    set((state) => ({
      messages: state.messages.filter((m) => m.id !== messageId),
    })),

  startStream: (messageId, name) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: messageId,
          content: "",
          role: "assistant",
          name,
          createdAt: new Date(),
          streaming: true,
        },
      ],
    })),

  appendToken: (messageId, token) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === messageId ? { ...m, content: m.content + token } : m,
      ),
    })),

  finalizeStream: (messageId) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === messageId ? { ...m, streaming: false } : m,
      ),
    })),
}));

export { useMessageStore };
