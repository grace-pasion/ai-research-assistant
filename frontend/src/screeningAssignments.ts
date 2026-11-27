import type { Paper, ProjectCollaborator } from "./types";

export type ScreeningAssignmentProgress = {
  userId: string;
  userName: string;
  assignedCount: number;
  completedCount: number;
  eligible: boolean;
};

export function summarizeScreeningAssignments(
  papers: Pick<Paper, "screening_assignments" | "screening_decisions">[],
  collaborators: Pick<ProjectCollaborator, "user_id" | "name" | "role">[],
): ScreeningAssignmentProgress[] {
  const progress = new Map<string, ScreeningAssignmentProgress>();
  for (const collaborator of collaborators) {
    if (collaborator.role === "read") continue;
    progress.set(collaborator.user_id, {
      userId: collaborator.user_id,
      userName: collaborator.name,
      assignedCount: 0,
      completedCount: 0,
      eligible: true,
    });
  }

  for (const paper of papers) {
    const decisions = new Set(paper.screening_decisions.map((decision) => decision.user_id));
    for (const assignment of paper.screening_assignments) {
      const reviewer = progress.get(assignment.user_id) ?? {
        userId: assignment.user_id,
        userName: assignment.user_name,
        assignedCount: 0,
        completedCount: 0,
        eligible: false,
      };
      reviewer.assignedCount += 1;
      if (decisions.has(assignment.user_id)) reviewer.completedCount += 1;
      progress.set(assignment.user_id, reviewer);
    }
  }

  return [...progress.values()].sort((left, right) =>
    left.userName.localeCompare(right.userName),
  );
}
