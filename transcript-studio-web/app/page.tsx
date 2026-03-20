"use client";

import { useCallback, useState } from "react";
import type { UploadResponse, JobDetail } from "@/lib/types";
import UploadStep from "@/components/UploadStep";
import TranscribeStep from "@/components/TranscribeStep";
import RefineStep from "@/components/RefineStep";
import ResultsStep from "@/components/ResultsStep";

function StepHeader({
  number,
  title,
  active,
  done,
}: {
  number: number;
  title: string;
  active: boolean;
  done: boolean;
}) {
  return (
    <div className="flex items-center gap-3 mb-3">
      <span
        className={`flex items-center justify-center w-7 h-7 rounded-full text-sm font-semibold
          ${done ? "bg-green-100 text-green-700" : active ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-400"}`}
      >
        {done ? "\u2713" : number}
      </span>
      <h2
        className={`text-lg font-semibold ${active || done ? "text-gray-900" : "text-gray-400"}`}
      >
        {title}
      </h2>
    </div>
  );
}

export default function Home() {
  const [uploadData, setUploadData] = useState<UploadResponse | null>(null);
  const [uploadFileName, setUploadFileName] = useState<string>("");
  const [job, setJob] = useState<JobDetail | null>(null);

  const hasUpload = !!uploadData;
  const hasTranscript = !!job?.raw_transcript;
  const hasRefined = !!job?.refined_transcript;

  const handleUploadComplete = useCallback(
    (data: UploadResponse, fileName: string) => {
      if (!data) {
        // "Change File" was clicked — reset
        setUploadData(null);
        setUploadFileName("");
        setJob(null);
        return;
      }
      setUploadData(data);
      setUploadFileName(fileName);
    },
    []
  );

  const handleReset = useCallback(() => {
    setUploadData(null);
    setUploadFileName("");
    setJob(null);
  }, []);

  return (
    <div className="space-y-6">
      {/* Step 1: Upload */}
      <section className="bg-white rounded-lg border border-gray-200 p-4 sm:p-6">
        <StepHeader number={1} title="Upload" active={true} done={hasUpload} />
        <UploadStep
          onUploadComplete={handleUploadComplete}
          uploadData={uploadData}
        />
      </section>

      {/* Step 2: Transcribe */}
      <section className="bg-white rounded-lg border border-gray-200 p-4 sm:p-6">
        <StepHeader
          number={2}
          title="Transcribe"
          active={hasUpload}
          done={hasTranscript}
        />
        <TranscribeStep
          jobId={uploadData?.job_id ?? ""}
          numChunks={uploadData?.num_chunks ?? 0}
          enabled={hasUpload}
          job={job}
          onJobUpdate={setJob}
        />
      </section>

      {/* Step 3: Refine */}
      <section className="bg-white rounded-lg border border-gray-200 p-4 sm:p-6">
        <StepHeader
          number={3}
          title="Refine"
          active={hasTranscript}
          done={hasRefined}
        />
        <RefineStep
          jobId={uploadData?.job_id ?? ""}
          enabled={hasTranscript}
          job={job}
          onJobUpdate={setJob}
        />
      </section>

      {/* Step 4: Results */}
      {hasRefined && job ? (
        <section className="bg-white rounded-lg border border-gray-200 p-4 sm:p-6">
          <StepHeader number={4} title="Results" active={true} done={true} />
          <ResultsStep job={job} onJobUpdate={setJob} />
        </section>
      ) : (
        <section className="bg-white rounded-lg border border-gray-200 p-4 sm:p-6 opacity-50">
          <StepHeader
            number={4}
            title="Results"
            active={false}
            done={false}
          />
          <p className="text-xs text-gray-400">No results yet</p>
        </section>
      )}

      {/* Reset button */}
      {hasUpload && (
        <div className="text-center pt-2 pb-4">
          <button
            onClick={handleReset}
            className="text-sm text-gray-400 hover:text-gray-600 transition-colors"
          >
            Reset &mdash; start over
          </button>
        </div>
      )}
    </div>
  );
}
