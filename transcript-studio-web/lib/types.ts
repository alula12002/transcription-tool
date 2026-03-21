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

/**
 * Build an UploadResponse from a completed JobDetail.
 * Used after async upload processing finishes.
 */
export function uploadResponseFromJob(job: JobDetail): UploadResponse {
  return {
    job_id: job.job_id,
    status: job.status,
    num_files_found: job.num_files_found,
    num_chunks: job.num_chunks,
    total_duration_seconds: job.total_duration_seconds,
    estimated_cost: job.upload_cost_estimate,
    skipped_files: job.skipped_files,
  };
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
