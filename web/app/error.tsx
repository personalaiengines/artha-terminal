"use client";
import { useEffect } from "react";
import { AlertTriangle, RotateCw } from "lucide-react";

// Route-segment error boundary. Keeps the app shell and shows a styled fallback
// instead of a blank page if any page throws during client render.
export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => { console.error(error); }, [error]);
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center text-center">
      <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-[var(--radius-lg)] bg-elevated hairline text-warn">
        <AlertTriangle size={24} />
      </div>
      <h2 className="text-[17px] font-semibold text-frost">Something went wrong on this view</h2>
      <p className="mt-1.5 max-w-sm text-[13px] text-muted">
        The page hit an unexpected error. Your data is safe — retry to reload just this view.
      </p>
      <button
        onClick={reset}
        className="mt-5 inline-flex items-center gap-2 rounded-[var(--radius-sm)] bg-accent px-4 py-2 text-[13px] font-medium text-white transition-opacity hover:opacity-90"
      >
        <RotateCw size={15} /> Retry
      </button>
    </div>
  );
}
