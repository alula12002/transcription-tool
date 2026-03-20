import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Transcript Studio",
  description: "Upload audio, transcribe, refine, download",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 min-h-screen antialiased">
        <header className="border-b border-gray-200 bg-white">
          <div className="max-w-3xl mx-auto px-4 py-4 sm:py-6 text-center">
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight">
              Transcript Studio
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              Upload audio, transcribe, refine, download
            </p>
          </div>
        </header>
        <main className="max-w-3xl mx-auto px-3 sm:px-4 py-4 sm:py-8">{children}</main>
      </body>
    </html>
  );
}
