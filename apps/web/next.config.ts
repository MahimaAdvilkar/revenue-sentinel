import type { NextConfig } from "next";

/**
 * Offline by construction.
 *
 * No image loader pointing at a remote host, no font CDN, no telemetry. The dashboard
 * talks to exactly one thing at runtime: the local FastAPI process. A test asserts the
 * built output references no external origin.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Next collects anonymous telemetry by default. This project makes "$0 spent, nothing
  // leaves the machine" a claim it can defend, so the collector is disabled here as well
  // as by `NEXT_TELEMETRY_DISABLED` in the Makefile.
  env: { NEXT_TELEMETRY_DISABLED: "1" },
};

export default nextConfig;
