export interface MessageCreatedPayload {
  messageId: string;
}

export interface StreamStartPayload {
  messageId: string;
  name: string;
}

export interface StreamTokenPayload {
  messageId: string;
  token: string;
}

export interface StreamEndPayload {
  messageId: string;
}

export interface SocketErrorPayload {
  message: string;
}

export interface MessagesPersistedPayload {
  mapping: { oldId: string; newId: string }[];
}

export interface SendMessagePayload {
  conversation_id: number;
  content: string;
}

export interface InitSessionPayload {
  conversation_id: number;
}

export interface ParticipantInfo {
  id: number;
  name: string;
}

export interface SessionReadyPayload {
  conversation_id: number;
  player: ParticipantInfo;
  characters: ParticipantInfo[];
}

export interface ServerToClientEvents {
  message_created: (payload: MessageCreatedPayload) => void;
  stream_start: (payload: StreamStartPayload) => void;
  stream_token: (payload: StreamTokenPayload) => void;
  stream_end: (payload: StreamEndPayload) => void;
  messages_persisted: (payload: MessagesPersistedPayload) => void;
  session_ready: (payload: SessionReadyPayload) => void;
  error: (payload: SocketErrorPayload) => void;
}

export interface ClientToServerEvents {
  send_message: (payload: SendMessagePayload) => void;
  init_session: (payload: InitSessionPayload) => void;
}

export type onOffType = <T extends keyof ServerToClientEvents>(event: T, handler: ServerToClientEvents[T]) => void;

// ---- Lore Creator namespace (/lore) ----

export interface LoreTokenPayload {
  token: string;
}

export interface LoreSavingPayload {
  title: string;
}

export interface LoreServerToClientEvents {
  lore_session_ready: (payload: { world_name: string }) => void;
  lore_token: (payload: LoreTokenPayload) => void;
  lore_saving: (payload: LoreSavingPayload) => void;
  lore_done: () => void;
  error: (payload: SocketErrorPayload) => void;
}

export interface LoreClientToServerEvents {
  init_lore_session: (payload: { world_name: string }) => void;
  lore_message: (payload: { content: string }) => void;
}

// ---- NPC Builder namespace (/npc-builder) ----

export interface NPCBuilderTokenPayload {
  token: string;
}

export interface NPCBuilderCreatedPayload {
  name: string;
}

export interface NPCBuilderServerToClientEvents {
  npc_builder_session_ready: (payload: { world_name: string }) => void;
  npc_builder_token: (payload: NPCBuilderTokenPayload) => void;
  npc_builder_created: (payload: NPCBuilderCreatedPayload) => void;
  npc_builder_done: () => void;
  error: (payload: SocketErrorPayload) => void;
}

export interface NPCBuilderClientToServerEvents {
  init_npc_builder: (payload: { world_name: string }) => void;
  npc_builder_message: (payload: { content: string }) => void;
}