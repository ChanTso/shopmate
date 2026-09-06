"use client";
import { Button } from "web-shared";
import type { BuyerCommand } from "@/lib/buyer-types";
import type { PendingBrowserWrite } from "@/lib/buyer-api";
export default function Commands({commands,local,session,disabled,onRetry,onLocalRetry,onSession}:{commands:BuyerCommand[];local:PendingBrowserWrite[];session:string;disabled:boolean;onRetry:(command:BuyerCommand)=>void;onLocalRetry:(key:string)=>void;onSession:(id:string)=>void}) {
 const unknown=commands.filter(command=>command.state==="unknown");
 const retained=local.filter(item=>!commands.some(command=>command.request_key===item.key));
 if(!unknown.length&&!retained.length)return null;
 return <section className="space-y-2 border-b border-(--warn) bg-(--warn-soft) px-4 py-3"><h2 className="font-semibold">以下写入结果尚未确认</h2><p className="text-xs">恢复只读取原回执，不会重新加车或下单。先核对原操作；明确继续时复用原请求身份。</p>{unknown.map(command=><details key={command.request_key} className="text-sm"><summary className="cursor-pointer">{command.operation} · {command.request_key}</summary><pre className="my-2 whitespace-pre-wrap break-all text-xs">{JSON.stringify(command.body,null,2)}</pre>{command.session_id&&command.session_id!==session?<Button variant="secondary" size="sm" disabled={disabled} onClick={()=>onSession(command.session_id!)}>打开原会话</Button>:<Button variant="secondary" size="sm" disabled={disabled} onClick={()=>onRetry(command)}>继续原操作（同一请求）</Button>}</details>)}{retained.map(item=><details key={item.key} className="text-sm"><summary className="cursor-pointer">浏览器未收到结果：{item.path}</summary><pre className="my-2 whitespace-pre-wrap break-all text-xs">{JSON.stringify(item.body,null,2)}</pre>{item.session!==session?<Button size="sm" disabled={disabled} onClick={()=>onSession(item.session)}>打开原会话</Button>:<Button variant="secondary" size="sm" disabled={disabled} onClick={()=>onLocalRetry(item.key)}>继续原请求</Button>}</details>)}</section>;
}
