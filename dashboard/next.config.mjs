/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Nothing repo-specific needed: reads happen at request time via the GitHub
  // Contents API (prod) or the local filesystem (dev), never at build time,
  // so no rewrites/redirects/env baking are required here.
};

export default nextConfig;
