"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { startTranscription, getJobStatus } from "@/lib/api";
import type { JobDetail } from "@/lib/types";
import ProgressBar from "./ProgressBar";

const POLL_INTERVAL = 2000;

export default function TranscribeStep({
  jobId,
  numChunks,
  enabled,
  job,
  onJobUpdate,
}: {
  jobId: string;
  numChunks: number;
  enabled: boolean;
  job: JobDetail | null;
  onJobUpdate: (job: JobDetail) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isTranscribing =
    job?.step === "transcribe" && job?.status === "processing";
  const isDone = !!job?.raw_transcript;

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const startPolling = useCallback(
    (id: string) => {
      stopPolling();
      pollingRef.current = setInterval(async () => {
        try {
          const status = await getJobStatus(id);
          onJobUpdate(status);
          if (status.status === "completed" || status.status === "failed") {
            stopPolling();
            if (status.status === "failed") {
              setError(status.error || "Transcription failed");
            }
          }
        } catch {
          stopPolling();
          setError("Lost connection to server");
        }
      }, POLL_INTERVAL);
    },
    [onJobUpdate, stopPolling]
  );

  useEffect(() => {
    return stopPolling;
  }, [stopPolling]);

  const handleTranscribe = useCallback(async () => {
    setError(null);
    try {
      await startTranscription(jobId);
      // Immediately set a processing state so UI updates
      onJobUpdate({
        job_id: jobId,
        status: "processing",
        step: "transcribe",
        progress: 0,
        error: null,
        num_files_found: 0,
        num_chunks: numChunks,
        total_duration_seconds: 0,
        upload_cost_estimate: 0,
        skipped_files: [],
        chunk_paths: [],
        raw_transcript: null,
        transcription_cost: 0,
        processing_time_seconds: 0,
        refined_transcript: null,
        refinement_mode: null,
        refinement_cost: 0,
        sections_processed: 0,
      });
      startPolling(jobId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start transcription");
    }
  }, [jobId, numChunks, onJobUpdate, startPolling]);

  if (isDone) {
    return (
      <div className="border border-green-200 bg-green-50 rounded-lg p-4">
        <p className="text-sm font-semibold text-gray-900">
          Transcription complete
        </p>
        <p className="text-sm text-gray-600 mt-1">
          Processing time: {job!.processing_time_seconds.toFixed(1)}s
          {job!.transcription_cost > 0 && (
            <> &middot; Cost: ${job!.transcription_cost.toFixed(2)}</>
          )}
        </p>
      </div>
    );
  }

  if (isTranscribing) {
    const currentChunk = Math.max(1, Math.ceil((job?.progress ?? 0) * numChunks));
    return (
      <div>
        <ProgressBar
          progress={job?.progress ?? 0}
          label={`Processing chunk ${currentChunk} of ${numChunks}...`}
        />
        <p className="text-xs text-amber-600 mt-2">
          Don&apos;t close this tab
        </p>
      </div>
    );
  }

  return (
    <div>
      <button
        disabled={!enabled}
        onClick={handleTranscribe}
        className="px-5 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 transition-colors disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed"
      >
        Transcribe
      </button>
      {!enabled && (
        <p className="text-xs text-gray-400 mt-2">Upload audio files first</p>
      )}
      {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
    </div>
  );
}
