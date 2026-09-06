"use client";
import { useEffect,useState } from "react";
import { Button,Notice } from "web-shared";
import { buyerApi,fetchProductsPage } from "@/lib/buyer-api";
import { useResource } from "@/lib/use-resource";
import type { Product } from "@/lib/buyer-types";
import ProductTile from "./ProductTile";
import { ProductDetail } from "./generative/ProductCarousel";
export default function Catalog({revision,onAdd}:{revision:number;onAdd?:(product:Product)=>Promise<boolean>}) {
 const [query,setQuery]=useState(""); const [draft,setDraft]=useState("");const[offset,setOffset]=useState(0);const[selected,setSelected]=useState<Product|null>(null);
 useEffect(()=>{buyerApi.page=selected?{page_type:"product",product_id:selected.product_id,query}:{page_type:"search",query};},[query,selected]);
 const {data,error}=useResource(()=>fetchProductsPage(query,offset),[query,offset,revision]);
 return <div className="space-y-4"><h1 className="text-2xl font-semibold">商品与规格</h1><form className="flex gap-2" onSubmit={e=>{e.preventDefault();setOffset(0);setSelected(null);setQuery(draft);}}><input aria-label="搜索商品" maxLength={256} value={draft} onChange={e=>setDraft(e.target.value)} placeholder="商品名称、品牌或用途" className="min-w-0 flex-1 rounded-lg border border-(--line) px-3 py-2"/><Button type="submit">搜索</Button></form>{error?<Notice>{error}</Notice>:!data?<p role="status">读取商品…</p>:<><p className="text-xs text-(--ink-soft)">本页 {data.products.length} 个目录项目；系列展开全部实际规格。</p><div className="grid grid-cols-2 gap-3 lg:grid-cols-3">{data.products.map(product=><ProductTile key={product.product_id} product={product} fluid selected={selected?.product_id===product.product_id} onOpen={setSelected} onAdd={onAdd}/>)}</div>{selected&&<ProductDetail key={selected.product_id} product={selected} onClose={()=>setSelected(null)} onAdd={onAdd}/>}<div className="flex justify-between"><Button variant="secondary" disabled={offset===0} onClick={()=>{setOffset(Math.max(0,offset-24));setSelected(null);}}>上一页</Button><span className="self-center text-sm">第 {Math.floor(offset/24)+1} 页</span><Button variant="secondary" disabled={data.next_offset==null} onClick={()=>{setOffset(data.next_offset!);setSelected(null);}}>下一页</Button></div></>}</div>;
}
