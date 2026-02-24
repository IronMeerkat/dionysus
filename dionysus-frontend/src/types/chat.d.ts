interface Message {
  id: string;
  content: string;
  role: "user" | "assistant";
  name: string;
  createdAt: Date;
  streaming?: boolean;
}

interface Conversation {
  id: string;
  name: string;
  messages: Message[];
}

interface PlayerOption {
  id: number;
  name: string;
}

interface CharacterOption {
  id: number;
  name: string;
}

interface Options{
  players: PlayerOption[];
  characters: CharacterOption[];
}