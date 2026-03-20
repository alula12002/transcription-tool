"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { JobDetail, RefinementMode } from "@/lib/types";
import { API_URL, startRefinement, getJobStatus } from "@/lib/api";
import ProgressBar from "./ProgressBar";

const POLL_INTERVAL = 2000;

const MODE_OPTIONS: { value: RefinementMode; label: string }[] = [
  { value: "raw_cleanup", label: "Raw Cleanup" },
  { value: "structured_prose", label: "Structured Prose" },
  { value: "summary", label: "Summary" },
];

export default function ResultsStep({
  job,
  onJobUpdate,
}: {
  job: JobDetail;
  onJobUpdate: (job: JobDetail) => void;
}) {
  const [viewMode, setViewMode] = useState<"raw" | "refined">("refined");
  const [reRefineMode, setReRefineMode] = useState<RefinementMode>("structured_prose");
  const [reRefineInstructions, setReRefineInstructions] = useState("");
  const [error, setError] = useState<string | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isReRefining = job.step === "refine" && job.status === "processing";

  const text =
    viewMode === "refined" ? job.refined_transcript : job.raw_transcript;

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
              setError(status.error || "Refinement failed");
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

  const handleDownload = (format: "txt" | "md") => {
    const content = viewMode === "refined" ? "refined" : "raw";
    window.open(
      `${API_URL}/download/${job.job_id}?content=${content}&format=${format}`,
      "_blank"
    );
  };

  const handleReRefine = useCallback(async () => {
    setError(null);
    try {
      await startRefinement(
        job.job_id,
        reRefineMode,
        reRefineInstructions.trim() || undefined
      );
      onJobUpdate({
        ...job,
        status: "processing",
        step: "refine",
        progress: 0,
        refined_transcript: null,
      });
      startPolling(job.job_id);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to start refinement"
      );
    }
  }, [job, reRefineMode, reRefineInstructions, onJobUpdate, startPolling]);

  // Show progress bar while re-refining
  if (isReRefining) {
    const sections = job.sections_processed || 3;
    const current = Math.max(1, Math.ceil((job.progress ?? 0) * sections));
    return (
      <div>
        <p className="text-sm font-medium text-gray-700 mb-2">
          Re-refining with {MODE_OPTIONS.find((m) => m.value === reRefineMode)?.label}...
        </p>
        <ProgressBar
          progress={job.progress ?? 0}
          label={`Refining section ${current} of ${sections}...`}
        />
        <p className="text-xs text-amber-600 mt-2">
          Don&apos;t close this tab
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Stats */}
      <div className="flex flex-wrap gap-3 text-sm text-gray-600">
        <span>
          Mode:{" "}
          <span className="font-medium">
            {job.refinement_mode?.replace("_", " ") ?? "—"}
          </span>
        </span>
        {job.sections_processed > 0 && (
          <span>
            &middot; Sections:{" "}
            <span className="font-medium">{job.sections_processed}</span>
          </span>
        )}
        {job.refinement_cost > 0 && (
          <span>
            &middot; Cost:{" "}
            <span className="font-medium">
              ${job.refinement_cost.toFixed(2)}
            </span>
          </span>
        )}
      </div>

      {/* View toggle */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit">
        <button
          onClick={() => setViewMode("raw")}
          className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors
            ${viewMode === "raw" ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"}`}
        >
          Raw Transcript
        </button>
        <button
          onClick={() => setViewMode("refined")}
          className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors
            ${viewMode === "refined" ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"}`}
        >
          Refined Transcript
        </button>
      </div>

      {/* Transcript text */}
      <div className="border border-gray-200 rounded-lg p-4 max-h-96 overflow-y-auto bg-gray-50">
        <pre className="text-sm text-gray-800 whitespace-pre-wrap font-sans leading-relaxed">
          {text}
        </pre>
      </div>

      {/* Download buttons */}
      <div className="flex gap-3">
        <button
          onClick={() => handleDownload("txt")}
          className="px-4 py-2 bg-gray-900 text-white text-sm font-medium rounded-md hover:bg-gray-800 transition-colors"
        >
          Download as TXT
        </button>
        <button
          onClick={() => handleDownload("md")}
          className="px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-50 transition-colors"
        >
          Download as MD
        </button>
      </div>

      {/* Re-refine section */}
      <div className="border-t border-gray-200 pt-4 mt-4">
        <p className="text-sm font-medium text-gray-700 mb-3">
          Try another mode without re-transcribing
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Mode</label>
            <select
              value={reRefineMode}
              onChange={(e) =>
                setReRefineMode(e.target.value as RefinementMode)
              }
              className="border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              {MODE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex-1 min-w-[200px]">
            <label className="block text-xs text-gray-500 mb-1">
              Additional context (optional)
            </label>
            <input
              type="text"
              value={reRefineInstructions}
              onChange={(e) => setReRefineInstructions(e.target.value)}
              placeholder="e.g. Focus on key stories"
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
          <button
            onClick={handleReRefine}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 transition-colors whitespace-nowrap"
          >
            Refine Again
          </button>
        </div>
        {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
      </div>
    </div>
  );
}
