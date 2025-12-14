import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Transpile react-day-picker to help Turbopack handle the ESM module
  transpilePackages: ["react-day-picker"],
  // Allow API calls to FastAPI backend
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
