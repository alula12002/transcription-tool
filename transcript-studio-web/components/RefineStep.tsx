"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { startRefinement, getJobStatus } from "@/lib/api";
import type { JobDetail, RefinementMode } from "@/lib/types";
import ProgressBar from "./ProgressBar";

const POLL_INTERVAL = 2000;

const MODE_LABELS: Record<RefinementMode, { label: string; desc: string }> = {
  raw_cleanup: {
    label: "Raw Cleanup",
    desc: "Light editing — fix filler words, false starts, grammar",
  },
  structured_prose: {
    label: "Structured Prose",
    desc: "Polished narrative with paragraphs and flow",
  },
  summary: {
    label: "Summary",
    desc: "Condensed overview of key points and themes",
  },
};

export default function RefineStep({
  jobId,
  enabled,
  job,
  onJobUpdate,
}: {
  jobId: string;
  enabled: boolean;
  job: JobDetail | null;
  onJobUpdate: (job: JobDetail) => void;
}) {
  const [mode, setMode] = useState<RefinementMode>("structured_prose");
  const [userInstructions, setUserInstructions] = useState("");
  const [parallel, setParallel] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollingRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isRefining = job?.step === "refine" && job?.status === "processing";
  const isDone = !!job?.refined_transcript;

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearTimeout(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  const startPolling = useCallback(
    (id: string) => {
      stopPolling();
      const poll = async () => {
        try {
          const status = await getJobStatus(id);
          onJobUpdate(status);
          if (status.status === "completed" || status.status === "failed") {
            pollingRef.current = null;
            if (status.status === "failed") {
              setError(status.error || "Refinement failed");
            }
          } else {
            pollingRef.current = setTimeout(poll, POLL_INTERVAL);
          }
        } catch {
          pollingRef.current = null;
          setError("Lost connection to server");
        }
      };
      pollingRef.current = setTimeout(poll, POLL_INTERVAL);
    },
    [onJobUpdate, stopPolling]
  );

  useEffect(() => {
    return stopPolling;
  }, [stopPolling]);

  // Safety net: if we should be polling but aren't (e.g. re-refine started
  // from ResultsStep which then unmounted), start polling
  useEffect(() => {
    if (isRefining && !pollingRef.current && jobId) {
      startPolling(jobId);
    }
  }, [isRefining, jobId, startPolling]);

  const handleRefine = useCallback(async () => {
    setError(null);
    try {
      await startRefinement(
        jobId,
        mode,
        userInstructions.trim() || undefined,
        parallel
      );
      onJobUpdate({
        ...job!,
        status: "processing",
        step: "refine",
        progress: 0,
        refined_transcript: null,
      });
      startPolling(jobId);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to start refinement"
      );
    }
  }, [jobId, mode, userInstructions, job, onJobUpdate, startPolling]);

  if (isDone) {
    return (
      <div className="border border-green-200 bg-green-50 rounded-lg p-4">
        <p className="text-sm font-semibold text-gray-900">
          Refinement complete
        </p>
        <p className="text-sm text-gray-600 mt-1">
          Mode: {MODE_LABELS[job!.refinement_mode as RefinementMode]?.label ?? job!.refinement_mode}
          {job!.sections_processed > 0 && (
            <> &middot; {job!.sections_processed} section{job!.sections_processed !== 1 ? "s" : ""}</>
          )}
          {job!.refinement_cost > 0 && (
            <> &middot; Cost: ${job!.refinement_cost.toFixed(2)}</>
          )}
        </p>
      </div>
    );
  }

  if (isRefining) {
    const sections = job?.sections_processed || 3;
    const current = Math.max(1, Math.ceil((job?.progress ?? 0) * sections));
    return (
      <div>
        <ProgressBar
          progress={job?.progress ?? 0}
          label={`Refining section ${current} of ${sections}...`}
        />
        <p className="text-xs text-amber-600 mt-2">
          Don&apos;t close this tab
        </p>
      </div>
    );
  }

  return (
    <div>
      {enabled ? (
        <div className="space-y-4">
          {/* Mode selector */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Mode
            </label>
            <div className="space-y-2">
              {(Object.entries(MODE_LABELS) as [RefinementMode, { label: string; desc: string }][]).map(
                ([key, { label, desc }]) => (
                  <label
                    key={key}
                    className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors
                      ${mode === key ? "border-blue-300 bg-blue-50" : "border-gray-200 hover:border-gray-300"}`}
                  >
                    <input
                      type="radio"
                      name="refine-mode"
                      value={key}
                      checked={mode === key}
                      onChange={() => setMode(key)}
                      className="mt-0.5"
                    />
                    <div>
                      <span className="text-sm font-medium text-gray-900">
                        {label}
                      </span>
                      <p className="text-xs text-gray-500">{desc}</p>
                    </div>
                  </label>
                )
              )}
            </div>
          </div>

          {/* User instructions */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Additional context{" "}
              <span className="font-normal text-gray-400">(optional)</span>
            </label>
            <textarea
              value={userInstructions}
              onChange={(e) => setUserInstructions(e.target.value)}
              placeholder="e.g. The speaker is my father, born in 1945. Preserve his storytelling style."
              rows={2}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          {/* Speed toggle */}
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={parallel}
              onChange={(e) => setParallel(e.target.checked)}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <span className="text-sm font-medium text-gray-700">
              ⚡ Fast mode
            </span>
            <span className="text-xs text-gray-400">
              (parallel processing — faster, but section transitions may be less smooth)
            </span>
          </label>

          {/* Refine button */}
          <button
            onClick={handleRefine}
            className="px-5 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 transition-colors"
          >
            Refine Transcript
          </button>

          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>
      ) : (
        <div>
          <button
            disabled
            className="px-5 py-2.5 bg-gray-200 text-gray-400 text-sm font-medium rounded-md cursor-not-allowed"
          >
            Refine Transcript
          </button>
          <p className="text-xs text-gray-400 mt-2">Transcribe audio first</p>
        </div>
      )}
    </div>
  );
}
