/**
 * Offline by construction.
 *
 * The dashboard must load with the network unplugged except for the local API. This
 * scans the **built output**, not the source, because a dependency can pull in a CDN
 * font or a beacon that no source file mentions.
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** Hosts that would mean the page phones home. */
const FORBIDDEN = [
  "fonts.googleapis.com",
  "fonts.gstatic.com",
  "cdn.jsdelivr.net",
  "unpkg.com",
  "cdnjs.cloudflare.com",
  "google-analytics.com",
  "googletagmanager.com",
  "vercel-insights.com",
  "vitals.vercel-insights.com",
];

function walk(dir: string, files: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    // Build caches contain compressed artefacts and source maps of dependencies; the
    // shipped client bundles and server chunks are what a browser actually receives.
    if (entry === "cache") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, files);
    else if (/\.(js|css|html)$/.test(entry)) files.push(full);
  }
  return files;
}

describe("offline runtime", () => {
  const built = walk(join(process.cwd(), ".next"));

  it("produced build output to inspect", () => {
    // Guards the whole suite from passing vacuously when `.next` is missing.
    expect(built.length).toBeGreaterThan(0);
  });

  it("references no external CDN, font, or analytics host", () => {
    const offenders: string[] = [];
    for (const file of built) {
      const content = readFileSync(file, "utf8");
      for (const host of FORBIDDEN) {
        if (content.includes(host)) offenders.push(`${host} in ${file}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("uses system fonts rather than a downloaded family", () => {
    const css = built.filter((file) => file.endsWith(".css"));
    const combined = css.map((file) => readFileSync(file, "utf8")).join("\n");

    expect(combined).toContain("system-ui");
    // `@font-face` with a remote src is the shape a hosted font would take.
    expect(combined).not.toMatch(/@font-face[^}]*https?:/);
  });
});
