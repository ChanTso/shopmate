// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";

import { AssistantPanel as PanelShell, type MerchantChat, type Prefill } from "web-shared";
import type { StagedChange } from "@/lib/types";
import GenerativeBlock from "./generative";

const COPY = {
  title: "ShopMate 经营助手",
  intro: "从已支付订单看经营变化，追问原因，再准备需要你批准的调价草案。",
  starters: [
    "最近 7 个完整 UTC 日的 CNY 销售额，相比前 7 天有什么变化？",
    "哪些商品贡献了最多成交额？请给出依据。",
    "查看可调价商品，并为其中一个准备降价 5% 的草案。",
    "查看本会话上次草案的执行结果。",
  ],
  label: "向经营助手发送消息",
  placeholder: "分析期间、商品贡献，或准备调价草案…",
};

export default function AssistantPanel({
  chat,
  prefill,
  onPrefill,
  ...shell
}: {
  chat: MerchantChat<StagedChange>;
  prefill: Prefill | null;
  onPrefill: (text: string) => void;
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
          onChangeAction={chat.busy ? undefined : chat.actOnChange}
          onPrefill={onPrefill}
        />
      )}
      {...shell}
    />
  );
}
