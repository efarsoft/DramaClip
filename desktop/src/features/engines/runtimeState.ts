export interface RuntimeState {
  installed: boolean | null;
  jobId: string;
  progress: number;
  stage: string;
  busy: boolean;
  install: () => void;
}
