# Agents

Main Agent 负责总体编排。内置 Sub Agent 包括 issue_analyzer、code_worker、code_reviewer、pr_reviewer 与 ci_analyzer。每个角色有独立系统提示、模型引用、能力和运行预算。

Agent 输出是建议。创建评论、Review、分支、PR 和 merge 等动作仍由 Controller 与 Policy 执行。
