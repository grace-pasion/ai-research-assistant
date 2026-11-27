import { describe, expect, it } from "vitest";
import { summarizeScreeningAssignments } from "./screeningAssignments";
import type { Paper, PaperScreeningAssignment, PaperScreeningDecision, ProjectCollaborator } from "./types";

function paper(
  assignments: PaperScreeningAssignment[],
  decisions: PaperScreeningDecision[] = [],
): Pick<Paper, "screening_assignments" | "screening_decisions"> {
  return { screening_assignments: assignments, screening_decisions: decisions };
}

function assignment(userId: string, userName: string): PaperScreeningAssignment {
  return {
    user_id: userId,
    user_name: userName,
    username: userName.toLowerCase().replace(/\s+/g, "_"),
    assigned_at: "2026-01-01T00:00:00Z",
  };
}

function decision(userId: string): PaperScreeningDecision {
  return {
    user_id: userId,
    user_name: userId,
    screening_status: "undecided",
    exclusion_reason: null,
    screening_note: "",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("screening assignment progress", () => {
  it("counts assigned papers and submitted decisions for each eligible collaborator", () => {
    const collaborators: ProjectCollaborator[] = [
      { user_id: "owner", username: "owner", name: "Owner", role: "owner" },
      { user_id: "reviewer", username: "reviewer", name: "Reviewer", role: "comment" },
      { user_id: "reader", username: "reader", name: "Reader", role: "read" },
    ];
    const papers = [
      paper(
        [assignment("owner", "Owner"), assignment("reviewer", "Reviewer")],
        [decision("owner")],
      ),
      paper([assignment("owner", "Owner")]),
    ];

    expect(summarizeScreeningAssignments(papers, collaborators)).toEqual([
      {
        userId: "owner",
        userName: "Owner",
        assignedCount: 2,
        completedCount: 1,
        eligible: true,
      },
      {
        userId: "reviewer",
        userName: "Reviewer",
        assignedCount: 1,
        completedCount: 0,
        eligible: true,
      },
    ]);
  });

  it("retains progress for assignments owned by collaborators who are no longer eligible", () => {
    expect(summarizeScreeningAssignments(
      [paper([assignment("former", "Former reviewer")])],
      [],
    )).toEqual([{
      userId: "former",
      userName: "Former reviewer",
      assignedCount: 1,
      completedCount: 0,
      eligible: false,
    }]);
  });
});
