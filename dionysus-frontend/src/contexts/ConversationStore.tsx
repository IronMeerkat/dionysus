import { create } from "zustand";
import type { ConversationListItem } from "../types/rest";
import { restService } from "../services/restService";

interface ConversationStoreState {
  conversations: ConversationListItem[];
  activeConversationId: number | null;
  activeConversationTitle: string | null;
  loading: boolean;
  page: number;
  total: number;
  setActiveConversation: (id: number | null, title: string | null) => void;
  renameConversation: (title: string) => Promise<void>;
  fetchConversations: (page?: number) => Promise<void>;
}

const useConversationStore = create<ConversationStoreState>((set, get) => ({
  conversations: [],
  activeConversationId: null,
  activeConversationTitle: null,
  loading: false,
  page: 1,
  total: 0,
  setActiveConversation: (id, title) => set({ activeConversationId: id, activeConversationTitle: title }),

  async renameConversation(title: string) {
    const { activeConversationId, conversations } = get();
    if (activeConversationId === null) return;
    try {
      const res = await restService.renameConversation(activeConversationId, title);
      set({
        activeConversationTitle: res.title,
        conversations: conversations.map((c) =>
          c.id === activeConversationId ? { ...c, title: res.title } : c,
        ),
      });
    } catch (err) {
      console.error("🔥 Failed to rename conversation", err);
    }
  },

  async fetchConversations(page = 1) {
    set({ loading: true });
    try {
      const res = await restService.getConversations(page);
      set({
        conversations: res.items,
        page: res.page,
        total: res.total,
        loading: false,
      });
    } catch (err) {
      console.error("🔥 Failed to fetch conversations", err);
      set({ loading: false });
    }
  },
}));

export { useConversationStore };
