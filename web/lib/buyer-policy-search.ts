export const POLICY_TOPICS = [
  { label: "退款与退换货", query: "退款" },
  { label: "配送与运费", query: "配送" },
  { label: "会员权益", query: "会员" },
  { label: "价格比较与价保", query: "价保" },
  { label: "保修与售后", query: "保修" },
  { label: "帐篷选购指南", query: "tent" },
  { label: "咖啡选购指南", query: "coffee" },
  { label: "书桌选购指南", query: "desk" },
];

export function policySearchQuery(input: string): string {
  const query = input.trim();
  if (!query) throw new Error("请输入政策关键词，或选择下方主题。");
  if (query.length > 200) throw new Error("政策关键词最多 200 个字符。");
  if (query.split(/\s+/).length > 8) throw new Error("政策查询最多使用 8 个以空格分隔的词，请缩短关键词。");
  return query;
}
