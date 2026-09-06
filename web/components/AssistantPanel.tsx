// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import { AssistantPanel as PanelShell, type MerchantChat, type Prefill } from "web-shared";
import type { StagedChange } from "@/lib/types";
import GenerativeBlock from "./generative";

const COPY = {
  title: "ShopMate 经营助手",
  intro: "结合成交、流量、商品和库存分析经营，再准备需要你批准的方案。",
  starters: [
    "当前报告期间的成交、流量和转化，相比上一期间有什么变化？",
    "哪些商品贡献了最多成交额？请给出依据。",
    "检查库存提醒和商品内容，提出有依据的改进方案。",
    "分析已有营销计划的同期 ROAS，并提出预算或文案调整建议。",
  ],
  label: "向经营助手发送消息",
  placeholder: "分析经营、商品、库存，或准备经营方案…",
};

export default function AssistantPanel({
  chat,
  prefill,
  onPrefill,
  actionsDisabled,
  ...shell
}: {
  chat: MerchantChat<StagedChange>;
  prefill: Prefill | null;
  onPrefill: (text: string) => void;
  actionsDisabled?: boolean;
  newMemoryCount: number;
  onOpenActivity: () => void;
  onClose: () => void;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
}) {
  return (
    <PanelShell
      chat={chat}
      copy={COPY}
      prefill={prefill}
      renderBlock={(segment) => (
        <GenerativeBlock
          block={segment.block}
          status={segment.status}
          onChangeAction={chat.busy || actionsDisabled ? undefined : chat.actOnChange}
          onPrefill={onPrefill}
        />
      )}
      {...shell}
    />
  );
}
