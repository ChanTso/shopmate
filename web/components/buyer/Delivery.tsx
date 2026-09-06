"use client";
import { useState } from "react";
import { Button } from "web-shared";
import { buyerApi } from "@/lib/buyer-api";
import { minorMoney } from "@/lib/buyer-checkout";
import { localDateTime } from "@/lib/retail-format";
import type { DeliveryEstimate } from "@/lib/buyer-types";
export default function Delivery({disabled}:{disabled:boolean}) {
 const[data,setData]=useState<DeliveryEstimate|null>(null);const[busy,setBusy]=useState(false);const[error,setError]=useState<string|null>(null);
 async function read(){if(disabled||busy)return;setBusy(true);setError(null);setData(null);try{const result=await buyerApi.post<{estimate:DeliveryEstimate}>("/delivery/cart",{});setData(result.estimate);}catch(error){setError(error instanceof Error?error.message:"暂时无法估算配送");}finally{setBusy(false);}}
 return <section className="space-y-2 rounded-xl border border-(--line) p-4"><h2 className="font-semibold">配送咨询</h2><p className="text-xs text-(--ink-soft)">按当前整车实际数量查询，仅供参考；这里不选择、购买或收取配送费用。</p><Button variant="secondary" disabled={disabled||busy} onClick={()=>void read()}>{busy?"查询中…":"查询当前整车配送估算"}</Button>{error&&<p role="alert" className="text-(--danger)">{error}</p>}{data&&<><p className="text-xs">报价时间 {localDateTime(data.quotedAt,data.timeZone)} · 商品金额 {minorMoney(data.itemSubtotalMinor,data.currency)}</p>{data.options.map(option=><div key={option.code} className="rounded bg-(--well) p-2 text-sm"><strong>{option.method} · {minorMoney(option.feeMinor,data.currency)}</strong>{option.earliestDate&&<p>预计 {option.earliestDate} 至 {option.latestDate} · {data.timeZone}</p>}{option.readyAt&&<p>可提货 {localDateTime(option.readyAt,data.timeZone)}</p>}{option.location&&<p>{option.location}</p>}</div>)}</>}</section>;
}
