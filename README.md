# 科研文件智能检索 — 三方向 Skill 集（challenge-139745c7）

三个相互独立、可单独安装运行的 Skill bundle，面向同一运行时契约
（/input/case.json + task.md，Skill 安装于 /skills/weekly-skill）：

| 目录 | 方向 | 核心交付 |
|-|-|-|
| [a-seekline-index](a-seekline-index/) | 确定性跨文件检索引擎 | BM25 索引 + 硬过滤查询 DSL + 逐字回链核验 |
| [b-claimlink-verify](b-claimlink-verify/) | 证据回链与核验协议 | 证据账本 + 机器审计 + 冲突/未找到登记 + 检索日志 |
| [c-libver-repair](c-libver-repair/) | 版本图谱与库修复 | 去重/版本族/canonical 规范库 + 恢复日志 + 元数据 manifest |

每个 bundle 自洽：自带 SKILL.md、脚本（Python 3 标准库）与参考文档，
互不依赖。全部脚本在合成测试库上做过端到端冒烟测试。
