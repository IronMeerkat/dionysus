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

export interface SendMessagePayload {
  conversationId: string;
  content: string;
}

export interface InitSessionPayload {
  playerId: number;
  characterIds: number[];
}

export interface ParticipantInfo {
  id: number;
  name: string;
}

export interface SessionReadyPayload {
  player: ParticipantInfo;
  characters: ParticipantInfo[];
}

export interface ServerToClientEvents {
  stream_start: (payload: StreamStartPayload) => void;
  stream_token: (payload: StreamTokenPayload) => void;
  stream_end: (payload: StreamEndPayload) => void;
  session_ready: (payload: SessionReadyPayload) => void;
  error: (payload: SocketErrorPayload) => void;
}

export interface ClientToServerEvents {
  send_message: (payload: SendMessagePayload) => void;
  init_session: (payload: InitSessionPayload) => void;
}
