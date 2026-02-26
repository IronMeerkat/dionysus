import { create } from "zustand";

interface MessageStoreState {
  messages: Message[];
  setMessages: (messages: Message[]) => void;
  addUserMessage: (content: string, playerName: string) => void;
  confirmUserMessage: (id: string) => void;
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
          id: null,
          content,
          role: "user",
          name: playerName,
          createdAt: new Date(),
        },
      ],
    })),

  confirmUserMessage: (id) =>
    set((state) => {
      const idx = state.messages.findIndex((m) => m.id === null);
      if (idx === -1) return state;
      const updated = [...state.messages];
      updated[idx] = { ...updated[idx], id };
      return { messages: updated };
    }),

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
