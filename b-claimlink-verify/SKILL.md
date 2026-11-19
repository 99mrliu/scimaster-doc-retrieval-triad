---
name: claimlink-verify
description: 证据回链与核验协议方向。先抽取全库文本为"事实层"，答案中每个论断必须先在证据账本登记三重定位证据卡（文件+sha256、页码+章节、逐字引文+字符区间），由独立脚本逐字核验引文与哈希，核验不过的论断禁止进答案；冲突登记两立场并按行政备注裁断，找不到的如实登记 not_found；全程检索动作写入只增不改的检索日志，使他人可重走路径。当任务强调"引用必须逐字可验、过程可复跑、冲突与缺失如实报告"时使用；输入为 /input/case.json + task.md + 文档库。
---

# claimlink-verify：证据回链与核验协议

## 解决什么问题

文件检索任务里"答案看上去对"与"答案可复核"是两回事。基础 Agent 的典型失败：
引文是改写而非原文、页码凭印象、只命中一份文件就下结论、两个版本互相矛盾
时被悄悄合并、没找到时含糊带过。本技能把核验做成**机器门槛**：

1. **事实层先行**：全部可抽取文本落盘 `/app/work/sources/` + manifest（含哈希）。
2. **先账本后答案**：每个论断登记证据卡；审计脚本逐字核验
   `quote` 与 `sha256`，**fail 的 claim 不允许进入答案**。
3. **冲突不合并**：两个来源不一致时登记双方立场 + 裁断依据（行政备注>版本序>
   时间戳），裁断后另一立场仍保留可查。
4. **找不到就说找不到**：`not_found` 记录搜索过什么、为什么不行。
5. **过程可重走**：`journal.py` 记录每次检索（考虑过几条、采纳几条、拒绝理由）。

## 适用条件 / 不适用

- 适用：结论必须逐字可验、可独立复跑的检索/整理任务；有版本冲突与副本的库。
- 不适用：允许改写、综述式归纳且无需定位的写作任务；库外开放网络检索。

## 环境依赖

Python ≥ 3.9 标准库；`pdftotext` 用于 PDF 文本抽取（缺失时 PDF 记
`no_pdf_tool`/`pdftotext_failed` 并列入 uncertainty）。无第三方包。

## 输入 / 输出契约

- 输入：`/input/case.json`（case_id + output_contract + 文档库路径 + 提问清单）、
  `/input/task.md`。库路径常见键 `library/library_root/data_dir/files`，
  提问常见键 `searches/questions/queries`；**以实际字段为准，先 `ls -R /input` 盘点**。
- 工作目录 `/app/work`；交付 `/app/output/`。`$S` = 技能目录（通常 `/skills/weekly-skill`）。
- 交付物：
  - `/app/output/result.json` —— 含 case_id 与 output_contract 全部字段 +
    诚实 status/sources/uncertainty/change_log
  - `/app/output/verification_report.json` —— 逐 claim 核验结果（核心审计件）
  - `/app/work/evidence_ledger.json` —— 证据账本（schema 见 references/evidence-schema.md）
  - `/app/work/search_journal.jsonl` —— 检索日志
  - `/app/work/sources/` —— 事实层（抽取文本 + manifest）

## 标准流程

**第 0 步 契约与骨架。** 读 case.json/task.md；立即
`python3 $S/scripts/make_result.py --case /input/case.json --out /app/output/result.json --init-only`

**第 1 步 事实层。**
`python3 $S/scripts/extract_all.py --lib <库根> --out /app/work/sources`
打开 manifest：`permission_denied / encrypted_pdf / unsupported_ext /
needs_ocr_or_empty` 的文件逐条列入 uncertainty 或 not_found 依据。

**第 2 步 逐提问检索（允许用任何手段，但必须记日志）。**
用 grep/python 定位候选文件与段落；每次检索：
`python3 $S/scripts/journal.py --work /app/work log --action "<做了什么>" --considered N --accepted M --note "<拒绝其余的理由>"`
候选命中多个版本/副本时，查行政备注（README/版本说明）确定正式版。

**第 3 步 建账本（本技能唯一需要大量判断的步骤）。**
写 `/app/work/evidence_ledger.json`：claims（一句一论断）、conflicts、not_found。
quote 必须**逐字复制**自抽取文本；来源写 sha256。

**第 4 步 机器审计（不可跳过）。**
`python3 $S/scripts/audit_claims.py --ledger /app/work/evidence_ledger.json --manifest /app/work/sources/sources_manifest.json --case /input/case.json --out /app/output/verification_report.json`
逐条看 checks：fail 的 claim 要么修引文重登，要么转 not_found；
uncovered 提问必须补 claim 或 not_found。修完重跑到
`n_fail=0` 或把剩余 fail 写进 result.json 的 uncertainty。

**第 5 步 组答案。**
只引用 `pass` 的 claim；冲突在答案中呈现裁断结论 + 另一立场出处。
写 `/app/work/answers.json`（键 = output_contract 字段）后：
`python3 $S/scripts/make_result.py --case /input/case.json --out /app/output/result.json --answers /app/work/answers.json --status <...> --sources <核验/日志/账本路径> --uncertainty "<未决项>"`

## 异常处置

| 情况 | 处置 |
|-|-|
| quote 逐字核验失败 | 检查是否改写/串页；修正 quote 或删除该 claim，禁止微调引文蒙混 |
| 文件哈希与登记不一致 | 说明文件中途变更，重新抽取该文件并更新账本 |
| 命中副本/旧版而提问未指定版本 | 转用正式版；无法确定正式版时记 conflict，双方并陈 |
| 提问的过滤条件（年份/编号/版本）不可满足 | 记 not_found + filter_check 说明，不放宽 |
| 扫描件无文本层 | 有 OCR 工具则抽取后照常；否则记 not_found，注明"存在但不可读" |
| 库缺提问所指文件 | 记 not_found，列出已检索范围；不写"应该没有" |

## 限制

- 核验覆盖"引文逐字 + 哈希 + 版本纪律 + 覆盖率"；论断的科学正确性由
  人工复核，本技能负责把依据钉死。
- 检索手段不限于本技能脚本（Agent 可自由 grep），但**凡被引用的证据必须
  过 audit_claims.py**——这是协议的底线，不是建议。

## 最小调用示例

见 examples/evidence-ledger.example.json（示意账本，已标注为示例）。
