---
name: libver-repair
description: 版本图谱与库修复方向。对科研文档库做 sha256 盘点（权限/损坏/加密/无文本层扫描件如实记录），用精确哈希+词 shingle 相似度+规范化基名三种证据合并版本族，按"行政备注>文件名版本标记>日期>mtime"裁断 canonical，物化无副本无旧版的规范库（canonical_library + 元数据 manifest + alias 映射），并为每个被排除/被标记的文件写恢复日志；检索提问只在规范库上作答，从结构上杜绝把副本和旧版本当成独立证据。当任务要求"整理文件、保留版本关系、去重、修复索引"时使用；输入为 /input/case.json + task.md + 文档库。
---

# libver-repair：版本图谱与库修复

## 解决什么问题

科研文件库的典型病灶：同一材料的改名副本散落多处、初稿/修订版/终稿并存、
扫描件无文本层、个别文件无权限或损坏。基础 Agent 在这种库上检索必然
"只命中一份就下结论"或"把 v1 当正式版"。本技能不直接"搜"，而是**先把库
修成一个可信的规范库**：

1. **盘点**：全库 sha256、大小、mtime、权限、可抽取性；问题文件逐条记录，
   不静默跳过。
2. **成族**：sha256 精确副本 + 词 5-gram 相似度（短文用包含度）+ 规范化基名
   三证据并查集合并版本族。
3. **裁断 canonical**：行政备注（引用原文）> 文件名版本标记
   （终稿>修订>初稿，vN 按数字）> 日期 > mtime；`副本/备份/copy` 路径在同分
   时天然落败。
4. **物化规范库**：`/app/output/canonical_library/` 只含 canonical 文件，
   相对路径不变；alias 映射、元数据 manifest（schema 见
   references/metadata-schema.md）、逐条恢复日志一并交付。
5. **规范库上作答**：提问只打 canonical 库，副本与旧版本在结构上不存在
   于答案空间。

## 适用条件 / 不适用

- 适用：任务含"整理/修复/建索引/保留版本关系/去重"或要求识别正式版；
  库中存在副本、修订链、扫描件、权限问题。
- 不适用：库本身不可访问（无读取权限的目录整体）；只要求单文件精读。

## 环境依赖

Python ≥ 3.9 标准库；`pdftotext` 用于 PDF 判定与抽取（缺失时 PDF 记
`no_pdf_tool`，照常入族与规范库但不提供文本字段）。无第三方包。

## 输入 / 输出契约

- 输入：`/input/case.json`（case_id + output_contract + 库路径 + 可能的
  提问/过滤条件）、`/input/task.md`。**以 case.json 实际字段为准；
  先用 `ls -R /input` 确认库根目录**。
- 工作目录 `/app/work`；交付 `/app/output/`。`$S` = 技能目录（通常
  `/skills/weekly-skill`）。
- 交付物：
  - `/app/output/result.json` —— 含 case_id 与 output_contract 全部字段 +
    诚实 status/sources/uncertainty/change_log
  - `/app/output/canonical_library/` —— 规范库（真实复制的文件）
  - `/app/output/canonical_manifest.json` —— 元数据清单（核心交付）
  - `/app/output/alias_map.json` —— 别名→canonical 映射
  - `/app/output/recovery_log.json` —— 跳过/排除/标记/恢复记录（核心审计件）
  - `/app/work/version_graph.json`、`/app/work/duplicates.json`、
    `/app/work/inventory.json` —— 中间证据图

## 标准流程

**第 0 步 契约与骨架。**
读 case.json/task.md；立即
`python3 $S/scripts/make_result.py --case /input/case.json --out /app/output/result.json --init-only`

**第 1 步 盘点。**
`python3 $S/scripts/lv_inventory.py --lib <库根> --out /app/work/inventory.json`
problem 类状态（permission_denied/encrypted/needs_ocr_or_empty/unsupported）
全部列入 result.json 的 uncertainty。

**第 2 步 去重。**
`python3 $S/scripts/lv_dedup.py --inventory /app/work/inventory.json --out /app/work/duplicates.json`
查看 exact_duplicate_groups（字节级副本）与 near_duplicate_groups
（相似度 ≥0.5，短文件用包含度）。

**第 3 步 版本图。**
`python3 $S/scripts/lv_version.py --inventory /app/work/inventory.json --duplicates /app/work/duplicates.json --out /app/work/version_graph.json`
检查 `admin_notes` 是否被正确解析；canonical 是否符合行政备注。若备注与
启发式冲突，以备注为准并修改 `demoted`/canonical 依据后重跑。

**第 4 步 修复物化。**
`python3 $S/scripts/lv_repair.py --inventory /app/work/inventory.json --duplicates /app/work/duplicates.json --graph /app/work/version_graph.json --outdir /app/output`
核对 recovery_log：每个非 canonical 文件必须有排除原因与去向。

**第 5 步 提问作答（如案例含提问）。**
`python3 $S/scripts/lv_qa.py --manifest /app/output/canonical_manifest.json --canon-root /app/output/canonical_library --question "<概念词，空格分隔>" --out /app/work/qa_qN.json`
答案写 `/app/work/answers.json`（键=output_contract 字段）后：
`python3 $S/scripts/make_result.py --case /input/case.json --out /app/output/result.json --answers /app/work/answers.json --status <...> --sources <manifest/recovery/version_graph 路径> --uncertainty "<未决项>"`

## 异常处置

| 情况 | 处置 |
|-|-|
| 无权限文件 | inventory 记 permission_denied；recovery_log 写明"需授权后重跑"；不进规范库 |
| 加密/损坏 PDF | 记 encrypted_pdf/extract_failed；保留在清单，不参与文本推断，注明修复途径 |
| 无文本层扫描件 | 记 needs_ocr_or_empty；文件进规范库但 status 标记；检索答案注明不可读 |
| 行政备注与文件名冲突 | 以行政备注为准；在 version_graph 的 admin_notes 保留引用，便于复核 |
| 无法确定 canonical（同分） | 按 mtime 取最新并在 uncertainty 说明；不随机选择 |
| 案例要求输出到特定路径/字段 | 以 output_contract 为准；本流程产物路径在 result.json 的 sources 中如实映射 |

## 限制

- 相似度基于词 5-gram；改写幅度极大的"同一材料"可能不成族——此时按
  规范化基名兜底，仍不成族则视为独立文件（不强行合并）。
- 行政备注解析是行级启发式；解析失败时备注原文仍在 admin_notes，
  供人工裁断。
- 规范库是复制而非移动；原库不做任何修改。

## 最小调用示例

```bash
python3 $S/scripts/lv_inventory.py --lib /input/library --out /app/work/inventory.json
python3 $S/scripts/lv_dedup.py --inventory /app/work/inventory.json --out /app/work/duplicates.json
python3 $S/scripts/lv_version.py --inventory /app/work/inventory.json \
    --duplicates /app/work/duplicates.json --out /app/work/version_graph.json
python3 $S/scripts/lv_repair.py --inventory /app/work/inventory.json \
    --duplicates /app/work/duplicates.json --graph /app/work/version_graph.json \
    --outdir /app/output
# 示意输出（演示数据，非正式案例结果）：
# repair: 9 canonical files, 3 aliases, 10 recovery entries -> /app/output
```
