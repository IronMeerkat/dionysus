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

export interface WorldResponse {
  id: number;
  name: string;
  description: string;
  entry_count: number;
}

export type IngestionStatus = "pending" | "ingested" | "failed";

export interface LoreEntryListItem {
  id: number;
  title: string;
  category: string | null;
  ingestion_status: IngestionStatus;
  created_at: string;
  updated_at: string;
}

// ---- Entity (Player / NPC) types ----

export interface EntityListItem {
  id: number;
  name: string;
  description: string | null;
  description_version: number | null;
  created_at: string;
}

export interface DescriptionVersion {
  version: number;
  body: string;
  created_at: string;
}

export interface EntityDetailResponse {
  id: number;
  name: string;
  created_at: string;
  descriptions: DescriptionVersion[];
}

export interface LoreEntryResponse {
  id: number;
  title: string;
  content: string;
  category: string | null;
  ingestion_status: IngestionStatus;
  world_id: number;
  created_at: string;
  updated_at: string;
}
