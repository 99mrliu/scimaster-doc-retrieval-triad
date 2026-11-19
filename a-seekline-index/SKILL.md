---
name: seekline-index
description: 确定性跨文件检索引擎方向。对科研文档库做一次性抽取建索引（PDF 逐页、Office 逐节、扫描件检测+可选 OCR、权限/损坏如实记录），用 JSON 查询 DSL 执行"概念检索 + 硬过滤"（年份、项目编号、文件类型、版本、路径、大小、时间为硬约束，无法满足如实报 no_match），每条命中携带 文件+哈希+物理页/印刷页+章节标题+段落首句+逐字引文+字符区间，并由独立核验脚本回读抽取文本逐字复核。当任务要求"在已有文件库中跨文件语义检索、章节级定位、按条件过滤并给出可回链证据"时使用；输入为 /input/case.json + task.md + 文档库。
---

# seekline-index：确定性跨文件检索引擎

## 解决什么问题

基础 Agent 做"库里找一段"的失败是系统性的：只按文件名匹配、命中旧版本或副本
而不自知、给出整篇文件而非章节段落、引文与原文对不上、过滤条件悄悄放宽。
本技能把检索做成**确定性的数据管线**：脚本负责抽取、索引、过滤、定位与核验，
Agent 只做两件需要判断的事——把提问翻译成查询 JSON、把核验过的命中写成答案。
同一文件库重复运行产出一致结果，每条证据可被第三方逐字复核。

## 适用条件 / 不适用

- 适用：文件已在本地库中（PDF/Word/PPT/Excel/文本/表格），需要跨文件概念检索、
  章节级定位、硬条件过滤、逐字可验的证据回链；需要如实处理副本/旧版本/无权限/
  扫描件。
- 不适用：开放网络文献检索；库中文件本身不存在（本技能只检索，不补造文件）；
  需要存储系统底层权限改造的任务。

## 环境依赖

Python ≥ 3.9 标准库即可运行全部脚本。`pdftotext`（poppler）用于 PDF 逐页抽取，
缺失时自动尝试 PyMuPDF，两者都没有则该 PDF 记入 `inventory.json` 的
`pdftotext_failed` 而不静默跳过。`tesseract`+`pdftoppm` 存在时对无文本层扫描页
自动 OCR，缺失则记 `needs_ocr`。无任何 pip 依赖，不要安装第三方包。

## 输入 / 输出契约

- 输入：`/input/case.json`（含 `case_id`、`output_contract`、文档库路径与检索提问）、
  `/input/task.md`。**先读实际文件；库路径与提问以 case.json 实际字段为准，
  常见键名 `library/library_root/data_dir/files` 与 `searches/questions/queries`；
  找不到时退而 `ls -R /input` 盘点。不要凭文件名猜内容。**
- 工作目录 `/app/work`；交付 `/app/output/`。`$S` = 技能安装目录（通常
  `/skills/weekly-skill`）。
- 交付物：
  - `/app/output/result.json` —— **必须含 case_id 与 output_contract 全部字段**，
    附诚实 `status` / `sources` / `uncertainty` / `change_log`
  - `/app/output/verify_report.json` —— 逐条命中核验结果（本方向核心审计件）
  - `/app/work/hits/*.json` —— 每问一份结构化命中（含全部被过滤拒绝的记录）
  - `/app/work/index/inventory.json` —— 全库盘点（哈希、权限、抽取状态）

## 标准流程（预算敏感：先骨架，后填实）

**第 0 步 读契约 + 存骨架（1 次模型请求内完成）。**
读 `/input/case.json` 与 `task.md`，确认库路径、提问清单、output_contract 字段；
立即写骨架：
`python3 $S/scripts/seek_result.py --case /input/case.json --out /app/output/result.json --init-only`

**第 1 步 建索引。**
`python3 $S/scripts/seek_ingest.py --lib <库根目录> --out /app/work/index`
产出逐页文本、章节表、印刷页映射、元数据（年份/项目号/版本标签/日期）与
BM25 索引。打开 `/app/work/index/inventory.json`，把无权限、损坏、加密、
needs_ocr、unsupported 的文件列入答案的 uncertainty。

**第 2 步 提问 → 查询 JSON（每问一个文件，DSL 见 references/query-dsl.md）。**
原则：`must` 放核心概念（AND）；同义/缩写/跨语言写法放 `any` 的 OR 组；
年份、项目编号、文件类型、版本等**一律放 `filters`，它们是硬约束**。
写 `/app/work/queries/qN.json`。

**第 3 步 检索。**
`python3 $S/scripts/seek_query.py --index /app/work/index --query /app/work/queries/qN.json --out /app/work/hits/qN.json`
`status=no_match` 表示库中无同时满足全部条件的文件——**如实报告，不要放宽
filters 重跑后声称满足**；确需放宽只能在 uncertainty 中写明放宽了什么。

**第 4 步 核验（不可跳过）。**
`python3 $S/scripts/seek_verify.py --index /app/work/index --hits /app/work/hits/q1.json ... --out /app/output/verify_report.json`
核验器回读抽取文本检查：引文逐字命中、首句在该页、章节标题存在、文件哈希未变。
任何 `verified=false` 的命中不得作为证据引用；修正定位或改查询后重跑。

**第 5 步 写答案 + 汇总 result.json。**
严格只用 `verified=true` 的命中作答，每个论断给出位置卡
（文件+版本+页码+章节+引文）。副本/旧版本命中要标注版本关系与理由
（优先引用行政备注指定的正式版）。写 `/app/work/answers.json`
（字段名 = output_contract 字段名），然后：
`python3 $S/scripts/seek_result.py --case /input/case.json --out /app/output/result.json --answers /app/work/answers.json --status <success|partial|no_match> --sources /app/output/verify_report.json /app/work/hits/q1.json ... --uncertainty "<每条未决事项>"`

## 异常处置

| 情况 | 处置 |
|-|-|
| 无权限文件 | inventory 记 `permission_denied`；答案注明"存在但不可读，未检索"，不得臆测内容 |
| 加密/损坏 PDF | 记 `encrypted_pdf` / `extract_failed`；列入 uncertainty |
| 无文本层扫描件 | 有 tesseract 则自动 OCR 并标注页；否则记 `needs_ocr`，该页不参与检索，答案说明 |
| 副本/备份命中 | 引擎对 `副本/备份/copy/backup` 路径降权；答案须说明哪个是正式版及依据 |
| 硬过滤无解 | 报 `no_match` 并附 filter_report（各条件拒绝数），不放宽 |
| 引文核验失败 | 不引用；修正或标 uncertainty，绝不改写引文去"通过" |

## 限制

- 语义对齐基于词元/BM25 + 可编辑同义词表（references/synonyms.json），
  不做向量嵌入；深层的"概念理解"由 Agent 在翻译查询时完成。
- 章节识别是启发式（标题行模式），无标题文档退化为页级+段落定位。
- 印刷页码映射依赖页眉页脚的页码标记；缺失时只给物理页并注明。

## 最小调用示例

见 examples/minimal-example.md（示意输出，已标注为示例，非正式案例结果）。
