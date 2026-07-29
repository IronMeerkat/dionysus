import { create } from 'zustand'

interface OptionsState {
    characters: CharacterOption[];
    setCharacters: (characters: CharacterOption[]) => void;
}

const useOptionsStore = create<OptionsState>((set) => ({
    characters: [],
    setCharacters: (characters) => set({ characters }),
}))


interface SessionState {
    player: CharacterOption | undefined;
    characters: CharacterOption[];
    setPlayer: (player: CharacterOption) => void;
    setCharacters: (characters: CharacterOption[]) => void;
}

const useSessionStore = create<SessionState>((set) => ({
    player: undefined,
    characters: [],
    setPlayer: (player) => set({ player }),
    setCharacters: (characters) => set({ characters }),
}));

export { useOptionsStore, useSessionStore };
