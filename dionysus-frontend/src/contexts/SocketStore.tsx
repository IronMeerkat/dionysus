import { create } from 'zustand'
import { SocketService } from "../services/socketService";
import type { onOffType, SendMessagePayload } from "../types/socket";

interface SocketStoreState {
    socket: SocketService;
    connectionId: number;
    setSocket: (socket: SocketService) => void;
    isConnected: () => boolean;
    connect: () => void;
    disconnect: () => void;
    sendMessage: (payload: SendMessagePayload) => void;
    initSession: (conversationId: number) => void;
    on: onOffType;
    off: onOffType;
}

const SOCKET_URL =
  import.meta.env.VITE_SOCKET_URL ?? `http://${window.location.hostname}:8000`;

const socketInstance = new SocketService();

export const useSocketStore = create<SocketStoreState>((set, get) => {
    socketInstance.onConnect = () => {
        set((s) => ({ connectionId: s.connectionId + 1 }));
    };

    return {
    socket: socketInstance,
    connectionId: 0,

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
    sendMessage: (payload: SendMessagePayload) => {
        const { socket } = get();
        socket.sendMessage(payload);
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
};});
