import type { CheckoutCommand, JavaCart } from "./buyer-types.ts";

/** Reject unsafe JSON integers before the browser sends a signed user's approval. */
export function checkoutCommand(cart: JavaCart): CheckoutCommand {
  if (!cart.checkoutReady || !cart.currency || !cart.items.length || cart.items.length > 100 || !Number.isSafeInteger(cart.version) || cart.version < 0 || !Number.isSafeInteger(cart.subtotalMinor) || cart.subtotalMinor! < 1) throw new Error("购物车当前不能结账，请刷新报价并处理缺货或价格异常。");
  for (const item of cart.items) {
    if (!item.orderable || item.currency !== cart.currency || !Number.isSafeInteger(item.unitPriceMinor) || item.unitPriceMinor < 1 || !Number.isSafeInteger(item.productVersion) || item.productVersion < 1 || !Number.isSafeInteger(item.quantity) || item.quantity < 1 || item.quantity > 24) throw new Error("商品报价无法安全确认，请刷新购物车。");
  }
  return { expectedCartVersion: cart.version, currency: cart.currency, items: cart.items.map(item => ({ productId: item.productId, quantity: item.quantity, expectedProductVersion: item.productVersion, expectedUnitPriceMinor: item.unitPriceMinor })) };
}
export function minorMoney(value: number | null, currency: string | null): string {
  if (value == null || !currency || !Number.isSafeInteger(value)) return "金额待确认";
  return new Intl.NumberFormat("zh-CN", { style: "currency", currency }).format(value / 100);
}

export function parseMinorAmount(value: string): number {
  if (!/^(0|[1-9]\d*)(\.\d{1,2})?$/.test(value)) throw new Error("金额必须是正数，最多两位小数。");
  const [major, fraction = ""] = value.split(".");
  const minor = Number(major) * 100 + Number(fraction.padEnd(2,"0"));
  if (!Number.isSafeInteger(minor) || minor <= 0) throw new Error("金额超出可安全提交的范围。");
  return minor;
}
