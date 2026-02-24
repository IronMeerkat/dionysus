import { io, Socket } from "socket.io-client";
import type {
  ServerToClientEvents,
  ClientToServerEvents,
} from "../types/socket";

type TypedSocket = Socket<ServerToClientEvents, ClientToServerEvents>;

export class SocketService {
  private socket: TypedSocket | null = null;

  get connected(): boolean {
    return this.socket?.connected ?? false;
  }

  connect(url: string): void {
    if (this.socket?.connected) {
      console.warn("⚡ SocketService: already connected, skipping");
      return;
    }

    if (this.socket) {
      this.socket.connect();
      return;
    }

    this.socket = io(url, {
      transports: ["websocket"],
      autoConnect: true,
    });

    this.socket.on("connect", () => {
      console.log("🔌 SocketService: connected", this.socket?.id);
    });

    this.socket.on("disconnect", (reason) => {
      console.log("🔌 SocketService: disconnected —", reason);
    });

    this.socket.on("connect_error", (err) => {
      console.error("❌ SocketService: connection error —", err.message);
    });
  }

  disconnect(): void {
    if (this.socket) {
      console.log("🔌 SocketService: disconnecting…");
      this.socket.disconnect();
    }
  }

  sendMessage(conversationId: string, content: string): void {
    if (!this.socket?.connected) {
      console.error("❌ SocketService: cannot send — not connected");
      return;
    }
    this.socket.emit("send_message", { conversationId, content });
  }

  initSession(playerId: number, characterIds: number[]): void {
    if (!this.socket?.connected) {
      console.error("❌ SocketService: cannot init session — not connected");
      return;
    }
    this.socket.emit("init_session", { playerId, characterIds });
  }

  on<E extends keyof ServerToClientEvents>(
    event: E,
    handler: ServerToClientEvents[E],
  ): void {
    if (!this.socket) {
      console.error("❌ SocketService: cannot subscribe — no socket");
      return;
    }
    this.socket.on(event, handler as never);
  }

  off<E extends keyof ServerToClientEvents>(
    event: E,
    handler: ServerToClientEvents[E],
  ): void {
    if (!this.socket) return;
    this.socket.off(event, handler as never);
  }
}
