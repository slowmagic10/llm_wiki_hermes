# 流程与 SOP 模板

适用于标准操作流程、运维 Runbook、审批流程和应急处置步骤。

```markdown
---
title: "<流程或操作名称>"
type: runbook
status: draft
owner: "<流程负责人>"
updated: "YYYY-MM-DD"
domain: "<domain_id>"
customer_safe: false
rag: false
category:
  - sop
tags:
  - internal
  - procedure
summary: "<一句话说明何时执行本流程>"
system: "<涉及系统或业务>"
scenario: "<触发场景>"
risk_level: "<low/medium/high>"
approver: "<需要审批时填写>"
rollback_available: true
prerequisites:
  - "<权限、备份、窗口或输入材料>"
sources:
  - type: draft_import
    ref: "待补充正式流程、工单或验证记录"
---

# <流程或操作名称>

## 目标

<说明流程完成后应达到的状态。>

## 触发条件

- <什么时候执行>
- <什么情况下禁止执行>

## 角色与权限

| 角色 | 职责 | 所需权限 |
| --- | --- | --- |
|  |  |  |

## 执行前检查

- [ ] 已确认影响范围
- [ ] 已获得必要审批
- [ ] 已完成备份或回滚准备
- [ ] 已通知相关人员

## 操作步骤

1. <操作和预期结果>
2. <操作和预期结果>
3. <操作和预期结果>

## 完成验证

- [ ] <验证项和通过标准>
- [ ] <监控或日志检查>

## 回滚步骤

1. <回滚触发条件>
2. <回滚操作>
3. <回滚后的验证>

## 异常与升级

| 异常 | 立即措施 | 升级对象 |
| --- | --- | --- |
|  |  |  |

## 执行记录

| 时间 | 执行人 | 工单/审批号 | 结果 |
| --- | --- | --- | --- |
|  |  |  |  |
```
