interface Message {
  id: string | null;
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

interface CharacterOption {
  id: number;
  name: string;
}

interface Options{
  characters: CharacterOption[];
}