import { useContext } from "react";
import { SocketContext, type SocketContextValue } from "../contexts/SocketContext";

export function useSocket(): SocketContextValue {
  const ctx = useContext(SocketContext);
  if (!ctx) {
    throw new Error("useSocket must be used within a <SocketProvider>");
  }
  return ctx;
}
