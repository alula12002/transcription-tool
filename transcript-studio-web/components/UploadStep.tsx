"use client";

import { useCallback, useRef, useState } from "react";
import { uploadZip, uploadAudio } from "@/lib/api";
import type { UploadResponse } from "@/lib/types";

const AUDIO_EXTENSIONS = [".mp3", ".wav", ".m4a", ".ogg", ".flac"];
const ALL_EXTENSIONS = [".zip", ...AUDIO_EXTENSIONS];

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

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

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
        let result: UploadResponse;
        let displayName: string;

        if (fileArray.length === 1 && isZip(fileArray[0])) {
          displayName = fileArray[0].name;
          result = await uploadZip(fileArray[0]);
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
          result = await uploadAudio(audioFiles);
        }

        setFileName(displayName);
        onUploadComplete(result, displayName);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setUploading(false);
      }
    },
    [onUploadComplete]
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
              Uploading and processing...
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
              Supports .zip, .mp3, .wav, .m4a, .ogg, .flac
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
