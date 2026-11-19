# 最小调用示例（示意输出，非正式案例结果）

假设文档库在 `/input/library`，提问为："终稿里的缓冲液配方是什么？项目编号 NSFC-82373621"。

## 1. 建索引

```bash
python3 /skills/weekly-skill/scripts/seek_ingest.py \
    --lib /input/library --out /app/work/index
```

## 2. 写查询（人工/Agent 翻译提问）

`/app/work/queries/q1.json`：

```json
{
  "query_id": "q1",
  "must": ["缓冲液", "配方"],
  "any": [["MOF"], ["metal-organic framework"], ["金属有机框架"]],
  "filters": {"version": "final", "project_id": "NSFC-82373621"},
  "top_k": 5
}
```

## 3. 检索 + 核验

```bash
python3 /skills/weekly-skill/scripts/seek_query.py \
    --index /app/work/index --query /app/work/queries/q1.json \
    --out /app/work/hits/q1.json
python3 /skills/weekly-skill/scripts/seek_verify.py \
    --index /app/work/index --hits /app/work/hits/q1.json \
    --out /app/output/verify_report.json
```

## 4. 示意输出（命中片段为演示数据）

```json
{
  "query_id": "q1",
  "status": "ok",
  "hits": [{
    "rank": 1,
    "doc": {"rel_path": "项目ALPHA/开题报告_终稿_2023-06-15.md",
            "meta": {"year": 2023, "project_ids": ["NSFC-82373621"],
                     "version_tag": "终稿"}},
    "location": {"page_physical": 1, "page_printed": null,
                 "section_heading": "## 2 实验设计",
                 "paragraph_first_sentence": "正式实验使用批次 B2023-014 与 B2023-021 的酶活数据……",
                 "quote": "缓冲液配方：50 mM Tris-HCl, pH 7.4, 150 mM NaCl, 1 mM EDTA，室温保存。"},
    "verified": true
  }]
}
```

核验器若报 `quote_not_verbatim`，说明引用与抽取文本不一致——必须修正定位或
在 `uncertainty` 中说明，不得引用未通过核验的片段。
