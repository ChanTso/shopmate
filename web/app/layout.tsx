// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ShopMate 零售工作台",
  description: "买家购物、商家经营分析与人工确认工作台",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
