// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const host = process.env.SHOPMATE_API_URL ?? "http://127.0.0.1:8101";
    return [{ source: "/api/merchant/:path*", destination: `${host}/api/merchant/:path*` }];
  },
  transpilePackages: ["web-shared"],
};

export default nextConfig;
