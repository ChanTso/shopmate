/** Memory persistence is independent from completion of the business reply. */
export function memoryNotice(status: unknown): string | null {
  if (status === "unavailable") return "本次记忆未保存。你可以在记忆面板核对后，重新提出记忆请求；回答与已提交的业务操作不会因此撤销。";
  if (status === "revoked") return "本次记忆保存已按你的修改或清除操作取消，不会恢复已清除的内容。";
  return null;
}
