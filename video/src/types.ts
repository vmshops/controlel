export type SceneDef = {
  id: string;
  type: string;
  duration: number; // seconds
  [key: string]: any;
};

export type ProjectModel = {
  id: string;
  kind: string;
  title: string;
  subtitle?: string;
  fps: number;
  duration_seconds: number;
  music?: { file: string; volume?: number };
  scenes: SceneDef[];
};
