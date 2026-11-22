export type User = {
  user_id: string;
  email: string;
  name: string;
};

export type Project = {
  project_id: string;
  project_name: string;
  description: string;
  created_at: string;
  updated_at: string;
};

export type DocumentRecord = {
  document_id: string;
  project_id: string;
  filename: string;
  file_type: string;
  file_size: number;
  processing_status: string;
  processing_error: string | null;
  uploaded_at: string;
};

export type DocumentSearchResult = {
  document: DocumentRecord;
  excerpt: string;
};

export type Paper = {
  paper_id: string;
  external_paper_id: string;
  api_provider: string;
  title: string;
  abstract: string | null;
  publication_year: number | null;
  doi: string | null;
  paper_url: string | null;
  venue: string | null;
  citation_count: number | null;
  authors: { author_id: string; author_name: string }[];
  saved: boolean;
};

export type SearchResult = {
  query_id: string;
  provider: string;
  query: string;
  results: Paper[];
};

export type Source = {
  kind: "document" | "paper";
  source_id: string;
  title: string;
  excerpt: string;
  document_id: string | null;
  paper_id: string | null;
  paper_url: string | null;
};

export type Draft = {
  answer: string;
  sources: Source[];
  approval_token: string;
  review_required: true;
  message: string;
};

export type Message = {
  message_id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  reviewed: boolean;
  sources: Source[];
};

export type Conversation = {
  conversation_id: string;
  project_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages?: Message[];
};
