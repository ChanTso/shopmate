import assert from "node:assert/strict";
import test from "node:test";
import { registerHooks } from "node:module";
const hooks=registerHooks({resolve(specifier,context,nextResolve){if(specifier==="web-shared/api.ts")return{url:new URL("../../vendor/commerce-agents/examples/web-shared/api.ts",import.meta.url).href,shortCircuit:true};return nextResolve(specifier,context);}});
const { BuyerApi }=await import("./fixtures/legacy-buyer-api.ts");
const { ShopMateApi }=await import("../lib/api.ts");
hooks.deregister();
test("lost cart reply retains exact body and original key, explicit retry does not add a new intent",async()=>{
 const original=globalThis.fetch;const api=new BuyerApi("","/api/buyer");api.session="buyer-session";api.setToken("buyer-test-token");const bodies:string[]=[];
 try{globalThis.fetch=async(_,init)=>{bodies.push(String(init?.body));throw new TypeError("disconnected");};const body={productId:"sku/a?#",quantity:2};await assert.rejects(api.write("/cart/add",body,"stable/a?#"));body.quantity=9;assert.equal(api.pendingWrites().length,1);
 globalThis.fetch=async(input,init)=>{assert.equal(String(input),"/api/buyer/cart/add");assert.equal(new Headers(init?.headers).get("X-Session-Id"),"buyer-session");bodies.push(String(init?.body));return Response.json({cart:{},quote:{},command:{}});};await api.retryWrite("stable/a?#");assert.equal(bodies[0],bodies[1]);assert.deepEqual(JSON.parse(bodies[1]),{productId:"sku/a?#",quantity:2,request_key:"stable/a?#"});assert.equal(api.pendingWrites().length,0);
 }finally{globalThis.fetch=original;}
});
test("unknown checkout retry requires its original session and never silently switches owner token",async()=>{
 const original=globalThis.fetch;const api=new BuyerApi("","/api/buyer");api.session="first";
 try{globalThis.fetch=async()=>{throw new TypeError("offline");};await assert.rejects(api.write("/checkouts",{expectedCartVersion:2},"same"));api.session="other";let called=false;globalThis.fetch=async()=>{called=true;return Response.json({});};await assert.rejects(api.retryWrite("same"),/原会话/);assert.equal(called,false);
 }finally{globalThis.fetch=original;}
});
test("buyer and merchant tokens remain independent, and failed memory read is visibly unavailable",async()=>{
 const original=globalThis.fetch;const buyer=new BuyerApi("","/api/buyer");const merchant=new ShopMateApi("","/api/merchant");buyer.setToken("buyer-test");merchant.setToken("merchant-test");let message="";buyer.onReadError=value=>{message=value;};
 try{globalThis.fetch=async()=>Response.json({detail:"memory database unavailable"},{status:503});assert.equal(await buyer.fetchMemory(),null);assert.match(message,/memory database unavailable/);buyer.setToken(null);assert.equal(new Headers(merchant.headers()).get("Authorization"),"Bearer merchant-test");assert.equal(new Headers(buyer.headers()).has("Authorization"),false);
 }finally{globalThis.fetch=original;}
});
test("buyer stop aborts the streaming body; later turn uses a new signal",async()=>{
 const original=globalThis.fetch;const api=new BuyerApi("","/api/buyer");let signal:AbortSignal;
 try{globalThis.fetch=async(_,init)=>{signal=init!.signal as AbortSignal;return new Response(new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode('event: text_delta\ndata: {"text":"读取中"}\n\n'));signal.addEventListener("abort",()=>controller.error(new DOMException("Aborted","AbortError")),{once:true});}}));};const stream=api.chatStream("看购物车");assert.equal((await stream.next()).value?.type,"text_delta");const next=stream.next();api.stopChat();await assert.rejects(next,/不会撤销/);assert.equal(signal!.aborted,true);globalThis.fetch=async(_,init)=>{assert.notEqual(init?.signal,signal);return new Response('event: turn_complete\ndata: {}\n\n');};assert.equal((await Array.fromAsync(api.chatStream("只读恢复")))[0].type,"turn_complete");
 }finally{api.stopChat();globalThis.fetch=original;}
});
