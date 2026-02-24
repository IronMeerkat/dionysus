export interface StoryBackgroundResponse {
  story_background: string;
}

export interface LocationResponse {
  location: string;
}

export interface MessageResponse {
  message: string;
}

export interface ApiError {
  status: number;
  message: string;
}
