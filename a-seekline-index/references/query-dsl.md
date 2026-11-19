# seekline 查询 DSL 参考

把每个检索提问翻译成一份 JSON 查询文件（如 /app/work/queries/q1.json），交给
`seek_query.py` 执行。原则：**must 收紧语义，any 兜住同义表述，filters 是硬约束**。

## 字段

| 字段 | 类型 | 含义 |
|-|-|-|
| query_id | str | 提问标识，原样带入结果 |
| must | [str] | 必须全部出现的概念（AND）。每个概念命中同义扩展后的任一表面形式即可 |
| any | [[str]] | 每个子列表是一个 OR 组：至少命中组内一个概念。用于同义词/缩写/跨语言 |
| filters | dict | 硬过滤条件（见下）。**无法满足时返回 no_match，绝不放宽** |
| top_k | int | 返回条数上限（默认 8） |
| expand_synonyms | bool | 是否用 references/synonyms.json 扩展（默认 true） |

## filters（全部为硬约束）

| 键 | 语义 |
|-|-|
| file_type | 扩展名列表，无点：["pdf","docx","xlsx"] |
| year / year_min / year_max | 文件内或文件名推断的年份 |
| project_id | 项目编号（大小写不敏感，需出现在文本头部提取的项目号中） |
| version | 版本标签子串："final"、"v2"、"修订"、"终稿"（大小写不敏感） |
| path_prefix / path_glob | 相对路径前缀 / glob 模式 |
| exclude_glob | 排除模式（如 "*副本*"） |
| min_size / max_size | 字节数 |
| mtime_after / mtime_before | "YYYY-MM-DD" |

## 概念拆分提示（中文科研材料）

- 化合物/材料：中英文名、缩写各进一个 any 组，如
  `["MOF"], ["metal-organic framework", "金属有机框架"]`。
- 实验条件：把方法名放 must，把缓冲液/温度等放 must 或独立 any 组。
- 提问若指定"哪一版/终稿/修订版"，用 filters.version + 行政备注佐证，
  不要只信文件名。
- 命中但落在旧版本/副本上的结果，在答案中标注版本关系并给出理由
  （README/版本说明里通常写了哪个是正式版）。
