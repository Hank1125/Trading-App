import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Meta Market",
  description: "Experimental virtual-points market on the Clash Royale and Rainbow Six Siege meta.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-zinc-50 text-zinc-900 antialiased">{children}</body>
    </html>
  );
}
