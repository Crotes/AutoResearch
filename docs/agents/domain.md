# 领域文档

本文件规定工程技能在探索代码库时如何读取和使用领域文档。

## 开始探索前应读取

- 仓库根目录下的 `GLOSSARY.md`
- 如果根目录存在 `GLOSSARY-MAP.md`，则按照其中的指引读取与当前任务相关的各上下文 `GLOSSARY.md`
- `docs/adr/` 中与当前工作区域有关的架构决策记录
- 对于多上下文仓库，还应检查 `src/<上下文>/docs/adr/` 中的上下文级决策

如果这些文件不存在，应直接继续，不要提示缺失，也不要预先建议创建。`/domain-modeling` 技能会在术语或决策真正得到确认时按需创建它们。

## 文件结构

单上下文仓库：

```text
/
├── GLOSSARY.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

多上下文仓库，以根目录存在 `GLOSSARY-MAP.md` 为标志：

```text
/
├── GLOSSARY-MAP.md
├── docs/adr/                          ← 系统级决策
└── src/
    ├── ordering/
    │   ├── GLOSSARY.md
    │   └── docs/adr/                  ← 上下文级决策
    └── billing/
        ├── GLOSSARY.md
        └── docs/adr/
```

## 使用术语表中的词汇

当输出内容需要命名领域概念时，例如问题标题、重构建议、假设或测试名称，应使用 `GLOSSARY.md` 中定义的术语，不要改用术语表明确排除的同义词。

如果需要的概念尚未出现在术语表中，这通常说明：

- 正在创造项目中并未使用的新词，应重新考虑；或者
- 领域文档确实存在缺口，应交由 `/domain-modeling` 处理

## 标明与架构决策的冲突

如果输出内容与现有 ADR 冲突，应明确指出，不得静默覆盖。例如：

> 与 ADR-0007（订单采用事件溯源）冲突，但值得重新讨论，因为……
