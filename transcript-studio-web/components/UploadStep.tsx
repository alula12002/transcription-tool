"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { uploadZip, uploadAudio, getJobStatus } from "@/lib/api";
import type { UploadResponse } from "@/lib/types";
import { uploadResponseFromJob } from "@/lib/types";
import ProgressBar from "./ProgressBar";

const AUDIO_EXTENSIONS = [".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm", ".aac"];
const ALL_EXTENSIONS = [".zip", ...AUDIO_EXTENSIONS];
const POLL_INTERVAL = 2000;

function isZip(file: File) {
  return file.name.toLowerCase().endsWith(".zip");
}

function isAudio(file: File) {
  return AUDIO_EXTENSIONS.some((ext) => file.name.toLowerCase().endsWith(ext));
}

function formatDuration(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export default function UploadStep({
  onUploadComplete,
  uploadData,
}: {
  onUploadComplete: (data: UploadResponse, fileName: string) => void;
  uploadData: UploadResponse | null;
}) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const pollingRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearTimeout(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  useEffect(() => {
    return stopPolling;
  }, [stopPolling]);

  const pollForCompletion = useCallback(
    (jobId: string, displayName: string) => {
      stopPolling();
      setProcessing(true);

      const poll = async () => {
        try {
          const job = await getJobStatus(jobId);

          if (job.status === "completed") {
            pollingRef.current = null;
            setProcessing(false);
            setUploading(false);
            const result = uploadResponseFromJob(job);
            setFileName(displayName);
            onUploadComplete(result, displayName);
          } else if (job.status === "failed") {
            pollingRef.current = null;
            setProcessing(false);
            setUploading(false);
            setError(job.error || "Upload processing failed");
          } else {
            pollingRef.current = setTimeout(poll, POLL_INTERVAL);
          }
        } catch {
          pollingRef.current = null;
          setProcessing(false);
          setUploading(false);
          setError("Lost connection to server");
        }
      };
      pollingRef.current = setTimeout(poll, POLL_INTERVAL);
    },
    [onUploadComplete, stopPolling]
  );

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      const fileArray = Array.from(files);
      if (fileArray.length === 0) return;

      // Validate file types
      const invalid = fileArray.filter(
        (f) => !ALL_EXTENSIONS.some((ext) => f.name.toLowerCase().endsWith(ext))
      );
      if (invalid.length > 0) {
        setError(
          `Unsupported file type: ${invalid.map((f) => f.name).join(", ")}`
        );
        return;
      }

      setError(null);
      setUploading(true);

      try {
        let response: { job_id: string; status: string };
        let displayName: string;

        if (fileArray.length === 1 && isZip(fileArray[0])) {
          displayName = fileArray[0].name;
          response = await uploadZip(fileArray[0]);
        } else {
          const audioFiles = fileArray.filter(isAudio);
          if (audioFiles.length === 0) {
            setError("No valid audio files found");
            setUploading(false);
            return;
          }
          displayName =
            audioFiles.length === 1
              ? audioFiles[0].name
              : `${audioFiles.length} audio files`;
          response = await uploadAudio(audioFiles);
        }

        // Backend now returns immediately with status "processing".
        // Start polling for completion.
        if (response.status === "completed") {
          // Backwards compatibility: if the server returned full results
          // synchronously (e.g. local dev), use them directly.
          setFileName(displayName);
          setUploading(false);
          onUploadComplete(response as UploadResponse, displayName);
        } else {
          // Async mode: poll until processing is done.
          pollForCompletion(response.job_id, displayName);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed");
        setUploading(false);
      }
    },
    [onUploadComplete, pollForCompletion]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files) handleFiles(e.target.files);
    },
    [handleFiles]
  );

  // Show upload summary after successful upload
  if (uploadData && fileName) {
    return (
      <div className="border border-green-200 bg-green-50 rounded-lg p-5">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-sm font-semibold text-gray-900">{fileName}</p>
            <p className="text-sm text-gray-600 mt-1">
              {uploadData.num_files_found} audio file
              {uploadData.num_files_found !== 1 ? "s" : ""} found,{" "}
              {uploadData.num_chunks} chunk
              {uploadData.num_chunks !== 1 ? "s" : ""}
            </p>
            <p className="text-sm text-gray-600">
              Duration: {formatDuration(uploadData.total_duration_seconds)}
            </p>
            <p className="text-sm text-gray-600">
              Est. transcription cost:{" "}
              <span className="font-medium">
                ${uploadData.estimated_cost.toFixed(2)}
              </span>
            </p>
            {uploadData.skipped_files.length > 0 && (
              <p className="text-xs text-amber-600 mt-1">
                Skipped: {uploadData.skipped_files.join(", ")}
              </p>
            )}
          </div>
          <button
            onClick={() => {
              setFileName(null);
              onUploadComplete(null as unknown as UploadResponse, "");
            }}
            className="text-sm text-blue-600 hover:text-blue-800 font-medium"
          >
            Change File
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Show progress while server processes audio */}
      {processing ? (
        <div className="border border-blue-200 bg-blue-50 rounded-lg p-5">
          <ProgressBar
            progress={-1}
            label="Processing audio (converting, chunking)..."
          />
          <p className="text-xs text-gray-500 mt-2">
            File uploaded — server is preparing audio chunks
          </p>
        </div>
      ) : (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={handleDrop}
          onClick={() => inputRef.current?.click()}
          className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors cursor-pointer
            ${dragging ? "border-blue-400 bg-blue-50" : "border-gray-300 hover:border-gray-400"}`}
        >
          {uploading ? (
            <div className="flex flex-col items-center">
              <div className="h-10 w-10 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin mb-3" />
              <p className="text-sm font-medium text-gray-700">
                Uploading...
              </p>
            </div>
          ) : (
            <>
              <svg
                className="mx-auto h-10 w-10 text-gray-400 mb-3"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.5}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"
                />
              </svg>
              <p className="text-sm font-medium text-gray-700">
                {dragging
                  ? "Drop files here"
                  : "Drag and drop audio files or zip here"}
              </p>
              <p className="text-xs text-gray-400 mt-1">
                Supports .zip, .mp3, .wav, .m4a, .ogg, .flac, .webm, .aac
              </p>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  inputRef.current?.click();
                }}
                className="mt-3 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 transition-colors"
              >
                Browse Files
              </button>
            </>
          )}
        </div>
      )}

      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ALL_EXTENSIONS.join(",")}
        onChange={handleChange}
        className="hidden"
      />

      {error && (
        <p className="mt-2 text-sm text-red-600">{error}</p>
      )}
    </div>
  );
}
