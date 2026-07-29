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
  player: CharacterOption;
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
  created_at: string;
}

export interface LoreEntryListItem {
  id: number;
  title: string;
  created_at: string;
  updated_at?: string;
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

// ---- Character status effects ----

export type AdvantageState = "advantage" | "normal" | "disadvantage";

export interface CharacterStatusEffect {
  id: number;
  character_id: number;
  name: string;
  description: string;
  affects: string;
  roll_modifier: number;
  advantage: AdvantageState;
  negated_by: string[];
  negation_condition: string | null;
  created_at: string;
  updated_at: string;
}

export interface StatusEffectPayload {
  name: string;
  description: string;
  affects: string;
  roll_modifier: number;
  advantage: AdvantageState;
  negated_by: string[];
  negation_condition: string | null;
}

export interface EntityDetailResponse {
  id: number;
  name: string;
  created_at: string;
  descriptions: DescriptionVersion[];
  status_effects?: CharacterStatusEffect[];
}

export interface LoreEntryResponse {
  id: number;
  title: string;
  content: string;
  world_name?: string;
  created_at: string;
  updated_at?: string;
}

// ---- Campaign types ----

export interface CampaignListItem {
  id: number;
  name: string;
  lore_world: string;
  conversation_count: number;
  created_at: string;
}

export interface CampaignConversation {
  id: number;
  title: string;
  created_at: string;
}

export interface CampaignNpc {
  id: number;
  name: string;
}

export interface CampaignDetailResponse {
  id: number;
  name: string;
  lore_world: string;
  created_at: string;
  conversations: CampaignConversation[];
  npcs: CampaignNpc[];
}

// ---- Vector Memory API abstraction ----

export interface VectorMemoryApi {
  getEntries: () => Promise<LoreEntryListItem[]>;
  getEntry: (id: number) => Promise<LoreEntryResponse>;
  createEntry: (title: string, content: string) => Promise<LoreEntryResponse>;
  updateEntry: (id: number, title: string, content: string) => Promise<LoreEntryResponse>;
  deleteEntry: (id: number) => Promise<unknown>;
}
