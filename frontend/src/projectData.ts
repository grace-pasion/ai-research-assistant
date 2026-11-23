import type { Conversation, DocumentRecord, Paper } from "./types";

export type ProjectData = {
  documents: DocumentRecord[];
  papers: Paper[];
  conversations: Conversation[];
};

export async function fetchProjectData(
  projectId: string,
  request: <T>(path: string) => Promise<T>,
  isCurrentProject: () => boolean,
  onLoaded: (data: ProjectData) => void,
): Promise<void> {
  const [documents, papers, conversations] = await Promise.all([
    request<DocumentRecord[]>(`/api/projects/${projectId}/documents`),
    request<Paper[]>(`/api/projects/${projectId}/papers`),
    request<Conversation[]>(`/api/projects/${projectId}/assistant/conversations`),
  ]);
  if (isCurrentProject()) onLoaded({ documents, papers, conversations });
}
