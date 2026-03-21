export default function ProgressBar({
  progress,
  label,
}: {
  progress: number;
  label?: string;
}) {
  const indeterminate = progress < 0;
  const pct = indeterminate ? 0 : Math.round(progress * 100);

  return (
    <div>
      {label && (
        <p className="text-sm text-gray-600 mb-1">{label}</p>
      )}
      <div className="w-full bg-gray-200 rounded-full h-2.5 overflow-hidden">
        {indeterminate ? (
          <div
            className="bg-blue-600 h-2.5 rounded-full animate-pulse"
            style={{ width: "60%" }}
          />
        ) : (
          <div
            className="bg-blue-600 h-2.5 rounded-full transition-all duration-300"
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
      {!indeterminate && (
        <p className="text-xs text-gray-400 mt-1 text-right">{pct}%</p>
      )}
    </div>
  );
}
