import { ProjectModel } from './types';
import projects from './generated/projects.json';

export function loadProject(projectId: string): ProjectModel {
  const found = (projects as ProjectModel[]).find((p) => p.id === projectId);
  if (!found) {
    throw new Error(`Project ${projectId} not found`);
  }
  // minimal runtime normalization
  found.fps = found.fps || 30;
  return found;
}
