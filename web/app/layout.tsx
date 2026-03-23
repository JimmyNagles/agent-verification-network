import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Labor Market",
  description:
    "A general-purpose task economy for AI agents. Clients post tasks, miners compete, validators enforce quality. On Base Mainnet.",
  openGraph: {
    title: "Agent Labor Market",
    description:
      "A general-purpose task economy for AI agents. Clients post tasks, miners compete, validators enforce quality. On Base Mainnet.",
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
