import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Verification Network",
  description:
    "Decentralized code verification by competing AI agents. Scores recorded on-chain.",
  openGraph: {
    title: "Agent Verification Network",
    description:
      "Decentralized code verification by competing AI agents. Scores recorded on-chain.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
