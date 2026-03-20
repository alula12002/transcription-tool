export type JobStatus = "pending" | "processing" | "completed" | "failed";

export type RefinementMode = "raw_cleanup" | "structured_prose" | "summary";

export type ExportFormat = "txt" | "md";

export interface UploadResponse {
  job_id: string;
  status: JobStatus;
  num_files_found: number;
  num_chunks: number;
  total_duration_seconds: number;
  estimated_cost: number;
  skipped_files: string[];
}

export interface JobDetail {
  job_id: string;
  status: JobStatus;
  step: string;
  progress: number;
  error: string | null;
  num_files_found: number;
  num_chunks: number;
  total_duration_seconds: number;
  upload_cost_estimate: number;
  skipped_files: string[];
  chunk_paths: string[];
  raw_transcript: string | null;
  transcription_cost: number;
  processing_time_seconds: number;
  refined_transcript: string | null;
  refinement_mode: string | null;
  refinement_cost: number;
  sections_processed: number;
}

export type AppStep = "upload" | "transcribe" | "refine" | "results";
