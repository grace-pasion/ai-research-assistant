import { isProjectSectionView, type ProjectSectionView } from "./globalShortcuts";

export function projectSectionStorageKey(userId: string, projectId: string): string {
  return `fieldnotes:last-section:${userId}:${projectId}`;
}

export function parseRememberedProjectSection(value: string | null): ProjectSectionView | null {
  return isProjectSectionView(value) ? value : null;
}

export function readRememberedProjectSection(
  storage: Pick<Storage, "getItem">,
  userId: string,
  projectId: string,
): ProjectSectionView | null {
  return parseRememberedProjectSection(
    storage.getItem(projectSectionStorageKey(userId, projectId)),
  );
}

export function rememberProjectSection(
  storage: Pick<Storage, "setItem">,
  userId: string,
  projectId: string,
  section: ProjectSectionView,
): void {
  storage.setItem(projectSectionStorageKey(userId, projectId), section);
}

export function resolveProjectSection(
  remembered: ProjectSectionView | null,
  explicit?: ProjectSectionView,
): ProjectSectionView {
  return explicit ?? remembered ?? "home";
}
