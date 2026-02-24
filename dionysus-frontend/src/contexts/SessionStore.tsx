import { create } from 'zustand'

interface OptionsState {
    players: PlayerOption[];
    characters: CharacterOption[];
    setPlayers: (players: PlayerOption[]) => void;
    setCharacters: (characters: CharacterOption[]) => void;
}

const useOptionsStore = create<OptionsState>((set) => ({
    players: [],
    characters: [],
    setPlayers: (players) => set({ players }),
    setCharacters: (characters) => set({ characters }),
}))


interface SessionState {
    player: PlayerOption | undefined;
    characters: CharacterOption[];
    setPlayer: (player: PlayerOption) => void;
    setCharacters: (characters: CharacterOption[]) => void;
}

const useSessionStore = create<SessionState>((set) => ({
    player: undefined,
    characters: [],
    setPlayer: (player) => set({ player }),
    setCharacters: (characters) => set({ characters }),
}));

export { useOptionsStore, useSessionStore };