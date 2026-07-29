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
  CharacterStatusEffect,
  StatusEffectPayload,
  CampaignListItem,
  CampaignDetailResponse,
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
  getCharacters(): Promise<CharacterOption[]> {
    return request<CharacterOption[]>("/characters");
  },

  getOptions(): Promise<Options> {  
    return request<Options>("/session/options");
  },

  setupSession(playerId: number, characterIds: number[], campaignId: number): Promise<FromConversationResponse> {
    return request<FromConversationResponse>("/session/setup", {
      method: "POST",
      body: { player_id: playerId, character_ids: characterIds, campaign_id: campaignId },
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

  getEntry(id: number): Promise<LoreEntryResponse> {
    return request<LoreEntryResponse>(`/lore/entries/${id}`);
  },

  createEntry(worldName: string, title: string, content: string): Promise<LoreEntryResponse> {
    return request<LoreEntryResponse>(`/lore/worlds/${encodeURIComponent(worldName)}/entries`, {
      method: "POST",
      body: { title, content },
    });
  },

  updateEntry(id: number, title: string, content: string): Promise<LoreEntryResponse> {
    return request<LoreEntryResponse>(`/lore/entries/${id}`, {
      method: "PUT",
      body: { title, content },
    });
  },

  deleteEntry(id: number): Promise<MessageResponse> {
    return request<MessageResponse>(`/lore/entries/${id}`, {
      method: "DELETE",
    });
  },

  // ---- Characters ----

  getCharacterList(): Promise<EntityListItem[]> {
    return request<EntityListItem[]>("/characters/");
  },

  getCharacter(characterId: number): Promise<EntityDetailResponse> {
    return request<EntityDetailResponse>(`/characters/${characterId}`);
  },

  createCharacter(name: string, description: string): Promise<EntityDetailResponse> {
    return request<EntityDetailResponse>("/characters/", {
      method: "POST",
      body: { name, description },
    });
  },

  updateCharacterName(characterId: number, name: string): Promise<EntityDetailResponse> {
    return request<EntityDetailResponse>(`/characters/${characterId}`, {
      method: "PUT",
      body: { name },
    });
  },

  addCharacterDescription(characterId: number, body: string): Promise<EntityDetailResponse> {
    return request<EntityDetailResponse>(`/characters/${characterId}/description`, {
      method: "POST",
      body: { body },
    });
  },

  deleteCharacter(characterId: number): Promise<MessageResponse> {
    return request<MessageResponse>(`/characters/${characterId}`, {
      method: "DELETE",
    });
  },

  // ---- Character Status Effects ----

  createStatusEffect(
    characterId: number,
    payload: StatusEffectPayload,
  ): Promise<CharacterStatusEffect> {
    return request<CharacterStatusEffect>(`/characters/${characterId}/status_effects`, {
      method: "POST",
      body: { ...payload },
    });
  },

  updateStatusEffect(
    characterId: number,
    effectId: number,
    payload: StatusEffectPayload,
  ): Promise<CharacterStatusEffect> {
    return request<CharacterStatusEffect>(`/characters/${characterId}/status_effects/${effectId}`, {
      method: "PUT",
      body: { ...payload },
    });
  },

  deleteStatusEffect(characterId: number, effectId: number): Promise<MessageResponse> {
    return request<MessageResponse>(`/characters/${characterId}/status_effects/${effectId}`, {
      method: "DELETE",
    });
  },

  // ---- Campaigns ----

  getCampaigns(): Promise<CampaignListItem[]> {
    return request<CampaignListItem[]>("/campaigns");
  },

  getCampaign(campaignId: number): Promise<CampaignDetailResponse> {
    return request<CampaignDetailResponse>(`/campaigns/${campaignId}`);
  },

  createCampaign(name: string, loreWorld: string): Promise<CampaignDetailResponse> {
    return request<CampaignDetailResponse>("/campaigns", {
      method: "POST",
      body: { name, lore_world: loreWorld },
    });
  },

  deleteCampaign(campaignId: number): Promise<MessageResponse> {
    return request<MessageResponse>(`/campaigns/${campaignId}`, {
      method: "DELETE",
    });
  },

  deleteConversation(conversationId: number): Promise<MessageResponse> {
    return request<MessageResponse>(`/conversations/${conversationId}`, {
      method: "DELETE",
    });
  },

  // ---- Character Memories ----

  getCharacterMemoryEntries(campaignId: number, npcId: number): Promise<LoreEntryListItem[]> {
    return request<LoreEntryListItem[]>(
      `/character-memories/campaigns/${campaignId}/npcs/${npcId}/entries`,
    );
  },

  getCharacterMemoryEntry(id: number): Promise<LoreEntryResponse> {
    return request<LoreEntryResponse>(`/character-memories/entries/${id}`);
  },

  createCharacterMemoryEntry(
    campaignId: number,
    npcId: number,
    title: string,
    content: string,
  ): Promise<LoreEntryResponse> {
    return request<LoreEntryResponse>(
      `/character-memories/campaigns/${campaignId}/npcs/${npcId}/entries`,
      { method: "POST", body: { title, content } },
    );
  },

  updateCharacterMemoryEntry(id: number, title: string, content: string): Promise<LoreEntryResponse> {
    return request<LoreEntryResponse>(`/character-memories/entries/${id}`, {
      method: "PUT",
      body: { title, content },
    });
  },

  deleteCharacterMemoryEntry(id: number): Promise<MessageResponse> {
    return request<MessageResponse>(`/character-memories/entries/${id}`, {
      method: "DELETE",
    });
  },
} as const;
