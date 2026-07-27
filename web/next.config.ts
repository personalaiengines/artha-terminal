import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone", // self-contained server bundle for a small Docker image
};

export default nextConfig;
