import { create } from 'zustand'
import { SocketService } from "../services/socketService";
import type { onOffType } from "../types/socket";

interface SocketStoreState {
    socket: SocketService;
    setSocket: (socket: SocketService) => void;
    isConnected: () => boolean;
    connect: () => void;
    disconnect: () => void;
    sendMessage: (content: string) => void;
    initSession: (conversationId: number) => void;
    on: onOffType;
    off: onOffType;
}

const SOCKET_URL =
  import.meta.env.VITE_SOCKET_URL ?? `http://${window.location.hostname}:8000`;

export const useSocketStore = create<SocketStoreState>((set, get) => ({
    socket: new SocketService(),

    setSocket: (socket) => set({ socket }),
    isConnected: () => {
        const { socket } = get();
        return socket.connected;
    },
    connect: () => {
        const { socket } = get();
        socket.connect(SOCKET_URL);
    },
    disconnect: () => {
        const { socket } = get();
        socket.disconnect();
    },
    sendMessage: (content: string) => {
        const { socket } = get();
        socket.sendMessage(content);
    },
    initSession: (conversationId: number) => {
        const { socket } = get();
        socket.initSession(conversationId);
    },
    on: (event, handler) => {
        const { socket } = get();
        socket.on(event, handler);
    },
    off: (event, handler) => {
        const { socket } = get();
        socket.off(event, handler);
    },
}));
