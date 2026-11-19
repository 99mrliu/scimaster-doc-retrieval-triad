# 证据账本（evidence ledger）schema

`/app/work/evidence_ledger.json` 是本的唯一事实出口：答案里允许出现的每个论断
都必须先在这里登记并通过机器核验。**先账本，后答案；账本上没有的，答案里
不允许出现。**

## 顶层结构

```json
{
  "claims": [ ... ],
  "conflicts": [ ... ],
  "not_found": [ ... ]
}
```

## claims[]（每条答案论断一条）

| 字段 | 必填 | 说明 |
|-|-|-|
| claim_id | 是 | 稳定编号，如 "c01" |
| question_id | 是 | 对应 case.json 里的提问标识；无法对应时写 "general" |
| claim_text | 是 | 写进答案的论断原文（一句话一个论断，不要一段三条） |
| about_version | 否 | 论断专门关于某个旧版本/副本时为 true（此时允许引用旧版） |
| evidence[] | 是 | 至少一条证据卡，见下 |

## evidence[]（证据卡，三重定位）

| 字段 | 必填 | 说明 |
|-|-|-|
| source_file | 是 | 库内相对路径，必须与 sources_manifest.json 一致 |
| source_sha256 | 是 | 登记时文件的 sha256；审计时复核，防文件被换 |
| page | 建议 | 物理页码（1 起）；已知印刷页时写 printed_page 附加字段 |
| section | 建议 | 章节标题原文 |
| quote | 是 | **逐字**原文片段（空白归一化后须能在该页命中），≤300 字符 |
| obtained_via | 是 | 怎么找到的：grep / index-query / browse / metadata |
| filter_check | 条件 | 提问带过滤条件时写明"满足：<条件>=<值>" |

## conflicts[]（冲突登记，不许悄悄二选一）

```json
{"topic": "缓冲液 Tris 浓度", "question_id": "q1",
 "positions": [
   {"value": "50 mM", "source_file": "...终稿...", "page": 1, "quote": "..."},
   {"value": "20 mM", "source_file": "...v2...", "page": 1, "quote": "..."}],
 "resolution": "以终稿为准", "resolution_basis": "README 行政备注指定终稿为正式版"}
```

## not_found[]（找不到就登记找不到）

```json
{"question_id": "q4", "sought": "2019 年扫描记录中的对照组数据",
 "searches": ["grep 对照组", "grep control", "browse scan_旧记录.pdf（无文本层）"],
 "conclusion": "无法确定", "reason": "该扫描件无文本层且 OCR 不可用"}
```

## 核验规则（audit_claims.py 自动执行）

1. quote 必须逐字命中 source_file 的抽取文本（空白归一化）。
2. source_sha256 必须与当前文件一致。
3. 引用了重复/旧版本文件而 `about_version` 不为 true → fail。
4. case.json 里每个提问都必须有 claim 覆盖，否则算 uncovered，
   必须用 not_found 说明原因。
