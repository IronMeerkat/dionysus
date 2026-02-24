import {
  createContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { SocketService } from "../services/socketService";

export interface SocketContextValue {
  socket: SocketService;
  isConnected: boolean;
}

export const SocketContext = createContext<SocketContextValue | null>(null);

const SOCKET_URL =
  import.meta.env.VITE_SOCKET_URL ?? `http://${window.location.hostname}:8000`;

export function SocketProvider({ children }: { children: ReactNode }) {
  const serviceRef = useRef(new SocketService());
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    const svc = serviceRef.current;
    svc.connect(SOCKET_URL);

    const pollId = setInterval(() => {
      setIsConnected(svc.connected);
    }, 500);

    svc.on("error", ({ message }) => {
      console.error("🚨 Socket server error:", message);
    });

    return () => {
      clearInterval(pollId);
      svc.disconnect();
    };
  }, []);

  return (
    <SocketContext.Provider
      value={{ socket: serviceRef.current, isConnected }}
    >
      {children}
    </SocketContext.Provider>
  );
}
