import type {
  StoryBackgroundResponse,
  LocationResponse,
  MessageResponse,
  ApiError,
  ConversationListResponse,
  FromConversationResponse,
  RenameConversationResponse,
} from "../types/rest";

const API_BASE =
  import.meta.env.VITE_API_URL ?? `http://${window.location.hostname}:8000`;

type HttpMethod = "GET" | "PUT" | "POST";

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

  setupSession(playerId: number, characterIds: number[], startNewConversation: boolean): Promise<MessageResponse> {
    return request<MessageResponse>("/session/setup", {
      method: "POST",
      body: { player_id: playerId, character_ids: characterIds, start_new_conversation: startNewConversation },
    });
  },

  getStoryBackground(): Promise<StoryBackgroundResponse> {
    return request<StoryBackgroundResponse>("/story_background");
  },

  updateStoryBackground(storyBackground: string): Promise<MessageResponse> {
    return request<MessageResponse>("/story_background", {
      method: "PUT",
      body: { story_background: storyBackground },
    });
  },

  getLocation(): Promise<LocationResponse> {
    return request<LocationResponse>("/location");
  },

  updateLocation(location: string): Promise<MessageResponse> {
    return request<MessageResponse>("/location", {
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
    return request<FromConversationResponse>("/session/from_conversation", {
      method: "PUT",
      body: { conversation_id: conversationId },
    });
  },

  renameConversation(conversationId: number, title: string): Promise<RenameConversationResponse> {
    return request<RenameConversationResponse>(`/conversations/${conversationId}/rename`, {
      method: "PUT",
      body: { title },
    });
  },
} as const;
