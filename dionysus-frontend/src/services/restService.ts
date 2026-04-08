import type {
  StoryBackgroundResponse,
  LocationResponse,
  MessageResponse,
  ApiError,
  ConversationListResponse,
  FromConversationResponse,
  RenameConversationResponse,
  WorldResponse,
  LoreEntryListItem,
  LoreEntryResponse,
  EntityListItem,
  EntityDetailResponse,
} from "../types/rest";

const API_BASE =
  import.meta.env.VITE_API_URL ?? `http://${window.location.hostname}:8000`;

type HttpMethod = "GET" | "PUT" | "POST" | "DELETE";

interface RequestOptions {
  method?: HttpMethod;
  body?: Record<string, unknown>;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { method = "GET", body } = opts;
  const url = `${API_BASE}${path}`;

  const init: RequestInit = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }

  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (err) {
    console.error(`❌ restService: network error — ${method} ${path}`, err);
    throw err;
  }

  if (!res.ok) {
    const apiError: ApiError = {
      status: res.status,
      message: `${res.status} ${res.statusText} — ${method} ${path}`,
    };
    console.error(`❌ restService: ${apiError.message}`);
    throw apiError;
  }

  return res.json() as Promise<T>;
}

export const restService = {
  getPlayers(): Promise<PlayerOption[]> {
    return request<PlayerOption[]>("/players");
  },

  getCharacters(): Promise<CharacterOption[]> {
    return request<CharacterOption[]>("/characters");
  },

  getOptions(): Promise<Options> {  
    return request<Options>("/session/options");
  },

  setupSession(playerId: number, characterIds: number[]): Promise<FromConversationResponse> {
    return request<FromConversationResponse>("/session/setup", {
      method: "POST",
      body: { player_id: playerId, character_ids: characterIds },
    });
  },

  getStoryBackground(conversationId: number): Promise<StoryBackgroundResponse> {
    return request<StoryBackgroundResponse>(`/conversations/${conversationId}/story_background`);
  },

  updateStoryBackground(conversationId: number, storyBackground: string): Promise<MessageResponse> {
    return request<MessageResponse>(`/conversations/${conversationId}/story_background`, {
      method: "PUT",
      body: { story_background: storyBackground },
    });
  },

  getLocation(conversationId: number): Promise<LocationResponse> {
    return request<LocationResponse>(`/conversations/${conversationId}/location`);
  },

  updateLocation(conversationId: number, location: string): Promise<MessageResponse> {
    return request<MessageResponse>(`/conversations/${conversationId}/location`, {
      method: "PUT",
      body: { location },
    });
  },

  getConversations(page = 1, pageSize = 20): Promise<ConversationListResponse> {
    return request<ConversationListResponse>(
      `/conversations/list?page=${page}&page_size=${pageSize}`,
    );
  },

  loadConversation(conversationId: number): Promise<FromConversationResponse> {
    return request<FromConversationResponse>(`/session/from_conversation/${conversationId}`);
  },

  renameConversation(conversationId: number, title: string): Promise<RenameConversationResponse> {
    return request<RenameConversationResponse>(`/conversations/${conversationId}/rename`, {
      method: "PUT",
      body: { title },
    });
  },

  editMessage(messageId: string, content: string): Promise<MessageResponse> {
    return request<MessageResponse>(`/messages/${messageId}`, {
      method: "PUT",
      body: { content },
    });
  },

  deleteMessage(messageId: string): Promise<MessageResponse> {
    return request<MessageResponse>(`/messages/${messageId}`, {
      method: "DELETE",
    });
  },

  // ---- Lore: Worlds ----

  getWorlds(): Promise<WorldResponse[]> {
    return request<WorldResponse[]>("/lore/worlds");
  },

  createWorld(name: string): Promise<WorldResponse> {
    return request<WorldResponse>("/lore/worlds", {
      method: "POST",
      body: { name },
    });
  },

  deleteWorld(worldName: string): Promise<MessageResponse> {
    return request<MessageResponse>(`/lore/worlds/${encodeURIComponent(worldName)}`, {
      method: "DELETE",
    });
  },

  // ---- Lore: Entries ----

  getWorldEntries(worldName: string): Promise<LoreEntryListItem[]> {
    return request<LoreEntryListItem[]>(`/lore/worlds/${encodeURIComponent(worldName)}/entries`);
  },

  getEntry(uuid: string): Promise<LoreEntryResponse> {
    return request<LoreEntryResponse>(`/lore/entries/${uuid}`);
  },

  createEntry(worldName: string, title: string, content: string): Promise<LoreEntryResponse> {
    return request<LoreEntryResponse>(`/lore/worlds/${encodeURIComponent(worldName)}/entries`, {
      method: "POST",
      body: { title, content },
    });
  },

  updateEntry(uuid: string, title: string, content: string): Promise<LoreEntryResponse> {
    return request<LoreEntryResponse>(`/lore/entries/${uuid}`, {
      method: "PUT",
      body: { title, content },
    });
  },

  deleteEntry(uuid: string): Promise<MessageResponse> {
    return request<MessageResponse>(`/lore/entries/${uuid}`, {
      method: "DELETE",
    });
  },

  // ---- Players ----

  getPlayerList(): Promise<EntityListItem[]> {
    return request<EntityListItem[]>("/players/");
  },

  getPlayer(playerId: number): Promise<EntityDetailResponse> {
    return request<EntityDetailResponse>(`/players/${playerId}`);
  },

  createPlayer(name: string, description: string): Promise<EntityDetailResponse> {
    return request<EntityDetailResponse>("/players/", {
      method: "POST",
      body: { name, description },
    });
  },

  updatePlayerName(playerId: number, name: string): Promise<EntityDetailResponse> {
    return request<EntityDetailResponse>(`/players/${playerId}`, {
      method: "PUT",
      body: { name },
    });
  },

  addPlayerDescription(playerId: number, body: string): Promise<EntityDetailResponse> {
    return request<EntityDetailResponse>(`/players/${playerId}/description`, {
      method: "POST",
      body: { body },
    });
  },

  deletePlayer(playerId: number): Promise<MessageResponse> {
    return request<MessageResponse>(`/players/${playerId}`, {
      method: "DELETE",
    });
  },

  // ---- NPCs ----

  getNpcList(): Promise<EntityListItem[]> {
    return request<EntityListItem[]>("/npcs/");
  },

  getNpc(npcId: number): Promise<EntityDetailResponse> {
    return request<EntityDetailResponse>(`/npcs/${npcId}`);
  },

  createNpc(name: string, description: string): Promise<EntityDetailResponse> {
    return request<EntityDetailResponse>("/npcs/", {
      method: "POST",
      body: { name, description },
    });
  },

  updateNpcName(npcId: number, name: string): Promise<EntityDetailResponse> {
    return request<EntityDetailResponse>(`/npcs/${npcId}`, {
      method: "PUT",
      body: { name },
    });
  },

  addNpcDescription(npcId: number, body: string): Promise<EntityDetailResponse> {
    return request<EntityDetailResponse>(`/npcs/${npcId}/description`, {
      method: "POST",
      body: { body },
    });
  },

  deleteNpc(npcId: number): Promise<MessageResponse> {
    return request<MessageResponse>(`/npcs/${npcId}`, {
      method: "DELETE",
    });
  },
} as const;
