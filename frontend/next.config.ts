import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle, so the runtime image carries only the
  // dependencies actually reached rather than the whole node_modules tree.
  output: "standalone",
};

export default nextConfig;
