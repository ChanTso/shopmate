import assert from "node:assert/strict";
import test from "node:test";
import { checkoutCommand,parseMinorAmount } from "../lib/buyer-checkout.ts";
import type { JavaCart } from "../lib/buyer-types.ts";
const cart: JavaCart = {version:7,currency:"CNY",subtotalMinor:3998,checkoutReady:true,items:[{productId:"sku-1",quantity:2,name:"桌灯",unitPriceMinor:1999,currency:"CNY",productVersion:3,stockQuantity:9,available:true,publicationState:"PUBLISHED",lineTotalMinor:3998,orderable:true,imageUrl:null,optionValues:{color:"白"},familyId:"lamp"}]};
test("checkout sends authoritative integer snapshot and excludes descriptive prices or delivery fees",()=>{
 assert.deepEqual(checkoutCommand(cart),{expectedCartVersion:7,currency:"CNY",items:[{productId:"sku-1",quantity:2,expectedProductVersion:3,expectedUnitPriceMinor:1999}]});
 assert.equal("delivery" in checkoutCommand(cart),false);
});
test("unsafe JSON integers, unavailable SKU and mixed currency cannot become browser approvals",()=>{
 assert.throws(()=>checkoutCommand({...cart,version:9007199254740992}),/不能结账/);
 assert.throws(()=>checkoutCommand({...cart,items:[{...cart.items[0],orderable:false}]}),/报价/);
 assert.throws(()=>checkoutCommand({...cart,items:[{...cart.items[0],currency:"USD"}]}),/报价/);
 assert.throws(()=>checkoutCommand({...cart,items:[{...cart.items[0],unitPriceMinor:19.99}]}),/报价/);
});
test("refund input uses decimal digits rather than float rounding and rejects fractional cents",()=>{
 assert.equal(parseMinorAmount("19.99"),1999);assert.equal(parseMinorAmount("0.01"),1);assert.equal(parseMinorAmount("0.29"),29);
 for(const value of ["1.001","1e2","0","-1","9007199254740992","NaN"])assert.throws(()=>parseMinorAmount(value));
});
