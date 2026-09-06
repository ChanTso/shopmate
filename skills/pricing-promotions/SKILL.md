---
name: pricing-promotions
description: 准备商品内容、价格、库存、促销和营销计划草案；先读真实对象，再预览、撤销重提和等待操作员批准，最多25个实际SKU。
---

# 草案与操作员批准

工具只准备、读取和取消。模型不具备apply_change；实际写入由操作员点击批准，Java事务按冻结版本校验并整批执行。聊天中的“批准”不能替代界面操作。

## 对象与约束

- 搜索实际ID，读get_listing详情／get_pricing_context后再提案；名字有歧义时澄清。family只是聚合，调价和补货必须指定实际variant；暂停、恢复和促销可指定family，由Java展开，最多25实际SKU。不拆批绕过一次审批范围。
- 普通调价必须published、available、无任何秒杀引用。工具有20%幅度上限，Java仍校验正价、币种、版本和可编辑性，但没有额外的20%规则。不要把观测成本当未经约定的底价。
- 用户给目标价按目标价；比例按刚读的当前价计算，整数分不得静默截断。需要取整但没有明确规则时列候选价确认。库存补货是1..500增量，不用旧库存算覆盖值；pause/activate不带quantity。零库存恢复available也不代表有货，草稿不能靠activate隐式发布。
- 内容字段沿工具真实白名单。family共享title/short_description/long_description/category在family上改；规格维度属于实际选项，不能借普通attributes更改size/color造成组合矛盾。先读完整文案再修改。

## 五类提案

- stage_price_update：实际SKU及新价，同币种，Java冻结旧价和版本。
- stage_listing_update：listing_id与需要修改的字段；不把价格、库存、权限、规格身份塞进文案属性。
- stage_inventory_action：restock增量，或pause/activate销售可用性。审批卡的stock是数量、available是布尔值，均不是钱。
- stage_promotion：正折扣大于0且不超过50%，确定实际范围、starts/ends；加价用普通调价。日期按真实上海操作日，裸结束日期包含该日、带offset时间结束排他。批准时真正写入新价；结束后不自动恢复，也没有夜间规则。尚未开始的批准返回promotion_not_started，草案仍待审；不要宣称失败终态或自动排程。
- stage_campaign：创建或更新营销计划，预算是计划而非已花费；不改现有spend/revenue观察。不声称已投放外部广告平台；缺失预算、归因收入或花费保持未知。

## 修订、恢复和读回

- 每种成功stage已返回可审阅卡片。准确区分旧值和提案值，说明仍待批准，不宣称业务已改变。
- 修改方案先取消旧草案，再新建；旧草案保留原参数。用返回change_id区分并存方案，不原地覆盖或先执行旧方案。
- 断连后get_pending_changes恢复原请求键的Java结果，不重复构造新意图。只有Java权威回执能说明是否执行。
- APPLIED=整批已应用，REJECTED=整批未执行，CANCELLED=取消，PREPARED=待审。取消已应用草案不能倒退业务状态；按实际返回结果解释。
- 操作员批准后读取商品／库存／营销记录和真实receipt，再说明结果。用户只要求保留方案时保持待审即可，不擅自批准。
