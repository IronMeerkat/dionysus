export interface StoryBackgroundResponse {
  story_background: string;
}

export interface LocationResponse {
  location: string;
}

export interface MessageResponse {
  message: string;
}

export interface ApiError {
  status: number;
  message: string;
}

export interface ConversationListItem {
  id: number;
  title: string;
}

export interface ConversationListResponse {
  items: ConversationListItem[];
  page: number;
  page_size: number;
  total: number;
}

export interface ConversationMessageDTO {
  id: string;
  content: string;
  role: "user" | "assistant";
  name: string;
  created_at: string;
}

export interface FromConversationResponse {
  id: number;
  title: string;
  player: PlayerOption;
  characters: CharacterOption[];
  messages: ConversationMessageDTO[];
}

export interface RenameConversationResponse {
  id: number;
  title: string;
}
