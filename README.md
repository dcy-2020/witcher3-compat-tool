# Witcher 3 Compat Tool

有限范围的《巫师 3》5.x 模组兼容扫描与可回滚修复工具。首版从一次实际的 4.04 → 5.00b/5.00c 修复中提取规则，使用 Python 标准库，运行时不需要联网。

**v0.1.0 是实验性命令行工具。** 自动修复仅覆盖函数参数、局部变量中的 `set` / `map` 命名冲突。扫描通过、应用成功都不等于游戏运行正常，也不等于全部模组已适配 5.x。

English: [README.en.md](README.en.md).

## 首版能做什么

| 功能 | 行为 |
| --- | --- |
| 脚本命名修复 | 词法识别函数参数和局部变量，将确定的引用一起改名；保留注释、字符串、成员名、编码和换行 |
| 重复脚本扫描 | 列出多个启用目录覆盖同一个脚本路径；标明是否存在合并输出，不推断加载优先级或合并正确性 |
| 旧格式提示 | 读取松散 `.w3strings` / CR2W 文件头，列出与指定参考版本不同的资源 |
| 复杂改动提示 | 标记角色、背包、能力管理脚本覆盖及 SSS 名称模组，供进一步检查 |
| 修复流程 | 生成候选副本、diff、SHA-256 清单；应用前重新计算候选并校验原文件；完整备份修改目标 |
| 回滚 | 默认只预览；明确执行时恢复原始字节；拒绝覆盖修复后的外部改动 |

以下功能尚未实现：原生脚本三方迁移、类字段与保存字段改名、自动合并、UI/模型重建、资源转换、字体汉化修复、天赋树适配、存档修改、游戏自动启动验证。`.bundle` 仅识别包头，内部资源不扫描；脚本之外的配置和注册表单也不修复。遇到这些问题会保持原文件。

## 下载与运行

需要 Python 3.10+。Windows 是主要使用平台；Linux 的合成测试覆盖通用逻辑，未验证 Linux 游戏运行效果。

[下载发布包](https://github.com/dcy-2020/witcher3-compat-tool/releases)。`.pyz` 单文件版无需安装工具包，直接使用 Python 运行：

```powershell
python witcher3-compat-tool-0.1.0.pyz --help
```

以下源码示例中的 `python -m w3compat` 可换成 `python witcher3-compat-tool-0.1.0.pyz`。源码 ZIP、单文件版和 SHA-256 校验文件均在发布页。

下载源码或发布包，解压后在工具目录执行：

```powershell
python -m w3compat --version
python -m w3compat --help
```

也可以在虚拟环境中安装 CLI（构建依赖可能需要联网）：

```powershell
python -m pip install .
w3compat --help
```

所有输出目录必须是新目录，放在游戏 `Mods`、`dlc`、`content`、`bin` 之外。示例的 `out` 是工具当前目录下的本地工作目录。每次扫描或分阶段生成使用新的目录名，工具不会覆盖旧结果。

## 使用流程

1. 扫描，不修改游戏。`--mod-settings` 可选；提供该文件才能排除 `Enabled=0` 的目录。未提供时只按目录名判断候选启用状态。

```powershell
python -m w3compat scan --game-root 'D:\Games\The Witcher 3' --mod-settings 'C:\Users\Player\Documents\The Witcher 3\mods.settings' --out out\scan-01
```

查看 `scan.md` / `scan.json`。相同引擎路径的重复脚本可能是既有合并结构；报告不会自动删除任何一份。资源参考版本默认为本案例观察到的 164，可用 `--expected-cr2w` / `--expected-strings` 更改。文件头不同只是检查线索，不能据此判断资源损坏。

2. 生成修复候选和 diff，仍不修改游戏。

```powershell
python -m w3compat stage --game-root 'D:\Games\The Witcher 3' --mod-settings 'C:\Users\Player\Documents\The Witcher 3\mods.settings' --out out\stage-01
```

查看 `preview.diff` 和 `plan.json`。阶段目录含原始脚本副本和候选副本，请保留在本机；它们可能包含游戏或第三方模组代码，不应提交到公共仓库。发生歧义的整个脚本不会生成部分修复。

3. 游戏关闭后应用。该命令就是写入授权，不会再弹交互确认。

```powershell
python -m w3compat apply --game-root 'D:\Games\The Witcher 3' --stage out\stage-01 --backup-dir out\transactions
```

工具会创建独立事务目录并返回其路径。它先备份并校验所有修改目标，再逐个原子替换。原文件变化、只读文件、符号链接/junction、候选篡改、检测到游戏进程时停止。候选必须逐字节等于当前工具重新运行规则的结果，修改清单中的哈希不能绕过这一检查。

工具仅写入启用名称的 `Mods/mod*/content/scripts/*.ws` 和非官方自定义 DLC 的同类脚本，以及根目录的 `.w3compat.lock` 协作锁文件。它不改原生 `content`、个人配置、存档、其他资源，也不结束游戏进程。读取 Windows 进程列表失败时停止写入。不要让其他编辑器或模组工具同时写这些文件。

4. 默认预览回滚；加 `--apply` 才实际还原。

```powershell
python -m w3compat rollback --game-root 'D:\Games\The Witcher 3' --transaction out\transactions\TRANSACTION-ID
python -m w3compat rollback --game-root 'D:\Games\The Witcher 3' --transaction out\transactions\TRANSACTION-ID --apply
```

如果应用过程中进程被中断，保留的 `prepared` / `failed_partial` 事务仍可检查并回滚。发现目标既不是原文件也不是已知修复文件时拒绝覆盖，保留外部编辑。单文件替换是原子的，多个文件的操作不保证电源中断时整体原子性。

5. 修复后使用原有工具核对合并来源，再实际启动游戏、检查设置菜单、读取已有存档，确认装备、按键、词条、天赋和所用模组功能。本工具没有更新 Script Merger 的 `MergeInventory.xml`，也没有替代其来源校验。游戏更新后应重新扫描；不要将 5.00c 的观察结论推广为未来版本兼容承诺。

## 测试与范围

```powershell
python -m unittest discover -s tests -v
```

本地验证包含真实旧备份中 56 个受影响脚本的只读分析（183 个标识符位置），以及对默认扫描选中的 49 个启用目录脚本副本进行分阶段生成、应用、逐字节回滚。7 个脚本处于 `~` 开头的非启用目录，仅做直接分析；扫描不会修改这些目录。原始游戏和模组源码未纳入项目。

这些验证只证明已描述规则和文件事务行为。此前完整游戏的运行结果来自另一套手工兼容修复，不能作为本工具完成全部迁移的证据。详情：[验证说明](docs/VALIDATION.md) / [规则边界](docs/RULES.md)。

## 开源与贡献

MIT 许可证仅覆盖本仓库原创工具代码、文档及合成测试。仓库不包含游戏代码、第三方模组、存档、个人配置、原始修复日志或打包资源，与 CD PROJEKT RED 无关联。

欢迎提交可复现的最小合成脚本和明确的错误信息。不要上传存档、个人目录、原始游戏文件、整套模组或访问凭据。新规则需要保守的失败分支、差异预览、回滚测试和运行验证范围说明。[贡献说明](CONTRIBUTING.md)。

参考工具：[WitcherScriptMerger](https://github.com/AnotherSymbiote/WitcherScriptMerger) 提供模组冲突检测与合并工作流。本项目未复制其实现，也不替代它。
