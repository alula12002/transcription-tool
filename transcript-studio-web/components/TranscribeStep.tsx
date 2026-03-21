"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { startTranscription, getJobStatus, API_URL } from "@/lib/api";
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
  const [parallel, setParallel] = useState(false);
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
      await startTranscription(jobId, "en", parallel);
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
  }, [jobId, numChunks, parallel, onJobUpdate, startPolling]);

  if (isDone) {
    return (
      <div className="border border-green-200 bg-green-50 rounded-lg p-4">
        <div className="flex items-start justify-between">
          <div>
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
          <button
            onClick={() => {
              window.open(
                `${API_URL}/download/${jobId}?content=raw&format=txt`,
                "_blank"
              );
            }}
            className="text-sm text-blue-600 hover:text-blue-800 font-medium flex items-center gap-1"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Download Raw
          </button>
        </div>
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
      {enabled && (
        <label className="flex items-center gap-2 mb-3 cursor-pointer">
          <input
            type="checkbox"
            checked={parallel}
            onChange={(e) => setParallel(e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <span className="text-sm text-gray-700">Fast mode</span>
          <span className="text-xs text-gray-400">
            (parallel — faster, but may inconsistently spell names across chunks)
          </span>
        </label>
      )}
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
