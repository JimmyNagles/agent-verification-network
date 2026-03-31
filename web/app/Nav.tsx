"use client";

import { useState } from "react";
import { useTheme } from "./ThemeProvider";

interface NavProps {
  active?: string;
}

export default function Nav({ active }: NavProps) {
  const { theme, toggleTheme } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);

  const links = [
    { href: "/jobs", label: "Job Board" },
    { href: "/leaderboard", label: "Leaderboard" },
    { href: "/become-a-client", label: "For Clients" },
    { href: "/become-a-worker", label: "For Workers" },
    { href: "/become-a-manager", label: "For Managers" },
  ];

  return (
    <div className="max-w-[1120px] mx-auto px-4 sm:px-6 pt-4">
      <nav className="glass px-4 sm:px-6 py-3.5" style={{ borderRadius: 14 }}>
        <div className="flex items-center justify-between">
          <a
            href="/"
            className="text-base sm:text-lg font-bold tracking-tight"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Agent Labor Market
          </a>

          {/* Desktop links */}
          <div className="nav-links-desktop text-sm" style={{ color: "var(--text-muted)" }}>
            {links.map((link) => (
              <a
                key={link.href}
                href={link.href}
                style={active === link.href ? { color: "var(--accent)", fontWeight: 600 } : {}}
              >
                {link.label}
              </a>
            ))}
            <button onClick={toggleTheme} className="theme-icon" title="Toggle theme">
              {theme === "dark" ? "\u2600" : "\u263E"}
            </button>
          </div>

          {/* Mobile toggle */}
          <div className="flex items-center gap-2">
            <button onClick={toggleTheme} className="theme-icon sm:hidden" title="Toggle theme" style={{ display: "none" }}>
              {theme === "dark" ? "\u2600" : "\u263E"}
            </button>
            <button
              className="nav-toggle"
              onClick={() => setMobileOpen(!mobileOpen)}
              aria-label="Toggle menu"
            >
              {mobileOpen ? "\u2715" : "\u2630"}
            </button>
          </div>
        </div>

        {/* Mobile menu */}
        <div className={`nav-mobile ${mobileOpen ? "open" : ""}`}>
          {links.map((link) => (
            <a
              key={link.href}
              href={link.href}
              style={active === link.href ? { color: "var(--accent)", fontWeight: 600 } : {}}
            >
              {link.label}
            </a>
          ))}
          <button
            onClick={toggleTheme}
            style={{ textAlign: "left", background: "none", border: "none", cursor: "pointer", fontFamily: "inherit" }}
          >
            {theme === "dark" ? "\u2600 Light mode" : "\u263E Dark mode"}
          </button>
        </div>
      </nav>
    </div>
  );
}
