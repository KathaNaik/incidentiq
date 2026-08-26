import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin the workspace root; otherwise Turbopack can infer a directory above the
  // repository when unrelated lockfiles exist higher up the filesystem.
  turbopack: { root: path.resolve(__dirname) },
};

export default nextConfig;
