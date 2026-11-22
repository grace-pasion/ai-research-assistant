export type User = {
  user_id: string;
  email: string;
  username: string | null;
  name: string;
  profile_picture: string | null;
};

export type Project = {
  project_id: string;
  user_id: string;
  team_workspace_id: string | null;
  project_name: string;
  description: string;
  created_at: string;
  updated_at: string;
};

export type TeamWorkspace = {
  team_workspace_id: string;
  owner_id: string;
  name: string;
  created_at: string;
  membership_role: "owner" | "member";
  member_count: number;
};

export type TeamWorkspaceMember = {
  user_id: string;
  username: string;
  name: string;
  email: string;
  role: "owner" | "member";
  joined_at: string;
};

export type TeamWorkspaceInvitation = {
  invitation_id: string;
  team_workspace_id: string;
  inviter_id: string;
  invitee_id: string;
  status: "pending" | "accepted" | "declined";
  created_at: string;
  updated_at: string;
  workspace_name: string;
  inviter_name: string;
  invitee_name: string;
  invitee_username: string;
  invitee_email: string;
};

export type TeamChannel = {
  channel_id: string;
  team_workspace_id: string;
  project_id: string | null;
  created_by: string;
  name: string;
  created_at: string;
  project_name: string | null;
};

export type TeamChannelMessage = {
  message_id: string;
  channel_id: string;
  sender_id: string;
  sender_name: string;
  content: string;
  created_at: string;
};

export type DocumentRecord = {
  document_id: string;
  project_id: string;
  filename: string;
  file_type: string;
  file_size: number;
  processing_status: "processing" | "ready" | "needs_api_key" | "failed" | "quota_exceeded";
  processing_error: string | null;
  uploaded_at: string;
};

export type BulkDocumentUploadResult = {
  filename: string;
  document: DocumentRecord | null;
  error: string | null;
};

export type BulkDocumentUploadResponse = {
  results: BulkDocumentUploadResult[];
};

export type AIUsageResponse = {
  assistant_prompts_used: number;
  assistant_prompts_limit: number;
  assistant_prompts_remaining: number;
  embedding_tokens_used: number;
  embedding_tokens_limit: number;
  embedding_tokens_remaining: number;
  resets_at: string;
};

export type DocumentSearchResult = {
  document: DocumentRecord;
  excerpt: string;
};

export type Annotation = {
  annotation_id: string;
  project_id: string;
  document_id: string | null;
  paper_id: string | null;
  quote: string | null;
  note: string;
  start_offset: number | null;
  end_offset: number | null;
  created_at: string;
  updated_at: string;
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
  screening_status: "unread" | "undecided" | "include" | "exclude";
  screening_note: string;
};

export type PaperImportResponse = {
  added_count: number;
  duplicate_count: number;
  results: {
    paper_id: string;
    title: string;
    doi: string | null;
    status: "imported" | "matched" | "duplicate";
  }[];
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
  page_number: number | null;
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

export type Colleague = {
  user_id: string;
  username: string;
  name: string;
  email: string;
};

export type ProjectInvitation = {
  invitation_id: string;
  project_id: string;
  inviter_id: string;
  invitee_id: string;
  status: "pending" | "accepted" | "declined";
  created_at: string;
  updated_at: string;
  invitee_name: string;
  invitee_username: string;
  invitee_email: string;
};

export type DirectMessage = {
  message_id: string;
  sender_id: string;
  recipient_id: string;
  content: string;
  created_at: string;
  read_at: string | null;
};

export type MessageThread = {
  user: Colleague;
  last_message: string;
  updated_at: string;
  unread_count: number;
};

export type Notification = {
  notification_id: string;
  kind: "project_invitation" | "invitation_response" | "message";
  actor_id: string;
  actor_name: string;
  actor_username: string | null;
  actor_email: string;
  project_id: string | null;
  project_name: string | null;
  invitation_id: string | null;
  invitation_status: "pending" | "accepted" | "declined" | null;
  message_id: string | null;
  created_at: string;
  read_at: string | null;
};
