import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";
const backend = process.env.FINALLY_BACKEND_URL ?? "http://localhost:8000";

// Production: static export served by FastAPI (contract §5).
// Dev: `next dev` on :3000 proxies /api/* to the backend. Rewrites only exist in
// dev because they are not supported by `output: 'export'`.
const nextConfig: NextConfig = {
  output: isDev ? undefined : "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  ...(isDev
    ? {
        async rewrites() {
          return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
        },
      }
    : {}),
};

export default nextConfig;
