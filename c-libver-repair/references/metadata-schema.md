# 元数据字段规范（canonical_manifest.json）

修复后的规范库中每个文件携带以下字段。字段值一律从文件内容与文件名推断，
推断不出来就留 `null` 并在 `recovery_log.json` 说明，**不补造**。

| 字段 | 来源 | 说明 |
|-|-|-|
| canonical_rel_path | 修复产物 | 规范库内相对路径（与原库一致） |
| source_rel_path | 原库 | 来源文件相对路径 |
| sha256 | 计算 | 内容哈希；副本/别名判定依据 |
| size / ext / file_type | 文件系统 | ext 带点，file_type 不带点 |
| version_label | 文件名标记 | final/revised/draft/vN/终稿/修订/初稿/预印本 |
| version_rank | 文件名标记 | 数值越大版本越新：final=300，revised=20，draft=10，vN=10×N |
| date | 文件名日期 | YYYY-MM-DD；用于版本链排序 |
| year | 文本头部/文件名 | 四位年份 |
| project_ids | 文本头部 | 形如 NSFC-82373621、BETA-2022-044 的编号 |
| title_guess | 首个标题行 | 启发式；仅作展示，不作判据 |
| status | 综合 | canonical / needs_ocr_or_empty 等 |

## 版本裁断优先级（version_graph.json 的 rules 同款）

1. **行政备注显式指定**（README/版本说明里"以 X 为准""X 为正式版""副本"等语句，
   引用原文入 `admin_notes[].quote`）；
2. **文件名版本标记**：终稿/final > 修订/revised > 初稿/draft/预印本；同档按 vN 数字；
3. **文件名日期**，再按 mtime；
4. 完全同格（精确副本）：非 `副本/备份/copy` 路径优先，其余按 mtime。

## 族的定义（family）

通过三种证据并查集合并：sha256 相同（精确副本）、词 5-gram 相似度
≥0.5（短文用包含度）、规范化基名相同（去版本标记/日期后的同目录同名
主体）。族内仅 canonical 文件进入规范库；其余文件在
`recovery_log.json` 记录排除原因与去向，**原文件不动**。
