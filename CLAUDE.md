# 仓库约定(必读)

本仓库 fork 自上游 ru(BnanZ0/ok-nte, remote 名 `upstream`),用户(龙威/longwei)的改动
遵循以下解耦约定,目的是把与上游的合并冲突面压到最小。**任何时候修改代码都必须遵守。**

## 用户代码放哪

- **`src/lw/` 是用户专属包**,所有整块新增的方法/常量/类一律放这里,通过 Mixin 接入上游类:
  - `combat_ext.py` → `CombatExtMixin`,接入 `BaseCombatTask`(CD锚定、角色不可用、队伍变更检测、trigger重载等)
  - `char_ext.py` → `CharExtMixin`,接入 `BaseChar`(通用技能打断恢复、输入重试、大招演出保护、空闲平A等)
  - `char_ui_ext.py` → `CharUIExtMixin`,接入 `CharUIMixin`(位于 `src/tasks/mixin/CharUIMixin.py`,大招菱形检测等)
  - `combat_templates.py` → LW 主C、增益辅助、治疗和早雾辅助角色模板
  - `resource_support.py` → `ResourceSupportMixin`,供增益辅助与治疗复用资源识别和 planner 执行骨架
  - `nte_task_ext.py` → `NTETaskExtMixin`,接入 `BaseNTETask`(find_confirm OCR认字等)
  - `sound_ext.py` → `SoundContextExtMixin`,接入 `SoundCombatContext`
  - `chars.py` → 用户角色注册表(`CharFactory.char_dict.update(lw_char_dict)`)
- 用户自有的完整文件(如 `src/char/Requiem.py`、`src/combat/requiem_combo.py`、
  `src/tasks/trigger/NanallySuperJumpTask.py`)不受此限,它们本身不与上游冲突。

战斗出招和切换已经统一迁移到 RU planner；旧 `do_perform`、旧 `Priority/Role` 和
planner A/B 总开关已经退役，不再新增兼容分支。

## RU 上游同步原则

- RU（`upstream`）是通用底层的持续演进基线，LW 是其上的定制差异层，不是另一套长期维护的底层分支。
- RU 更新通用接口、状态模型、异常模型、生命周期或算法时，原则上应完整升级到新基线，并在同一交付中把 LW 定制迁移到新接口；不得仅因现有 LW 依赖旧接口而保留旧 RU 实现。
- 上游同步必须保留的是用户明确要求的 LW 行为和结果，而不是其当前实现形式。若新 RU 底层影响 LW 定制，应在新基线上重新表达该定制，不能通过回退底层规避适配。
- 解决 RU 与 `[lw]` 冲突时，以最新 RU 实现为底稿，识别并重新应用 LW 行为差异；不得机械地以本地旧实现覆盖上游，也不得遗漏上游同一区域的新修复。
- 迁移完成后只保留一条生产运行路径。除非用户明确要求临时诊断，不得为了兼容旧 RU 接口保留别名、旧异常、旧方法副本、双实现或 A/B 开关；临时诊断路径验证完成后应删除。现有双路径属于待收敛技术债，相关区域升级时应一并迁移和清理，不得作为新增代码范式。
- 同步验证应围绕 LW 定制行为是否仍成立以及 RU 新行为是否生效编写回归测试，不以保留旧 RU 内部结构为目标。

## 智能体约定同步

- `CLAUDE.md` 是 Claude 的项目指令，`AGENTS.md` 是 Codex 的项目指令；两者共享的仓库约定必须保持同步。
- 修改任一文件中的共享约定时，必须同时检查并更新另一文件，避免 Claude 与 Codex 执行标准不一致。
- 仅适用于某一工具的专属指令应明确标注适用对象，无需机械复制到另一文件。

## `# [lw]` 标记

上游源文件里**凡带 `# [lw]` 注释的行/块都是用户改动**:
- 合并上游时必须保留这些标记所代表的用户行为意图，但不要求保留原代码形式；冲突时以最新
  RU 实现为底稿，在新接口和新生命周期上重新应用 LW 差异。
- 带 `[lw] 本方法被大幅改写` 的方法表示需要重点迁移，而不是“本地版本永远优先”。必须逐项
  比对 RU 对同一方法的新改动，把 LW 行为迁移到新基线，并清理被新底层替代的旧实现。
- 给上游文件新增用户逻辑时:能放 `src/lw/` 就放(上游文件只留一行接线),必须留在原地的
  改动压到最短并加 `# [lw]` 标记。**不要**在上游文件里写成片的用户代码。

## 技术限制

- Mixin 作为基类**不能 override** 上游类体里已定义的方法(Python MRO 子类优先)。
  要改上游方法的行为:
  - **小改动**(几行以内): 就地改 + `# [lw]` 标记;
  - **较大改动**: 优先在 RU 新实现中提取稳定扩展点或最小 hook，把 LW 行为放到 `src/lw/`，
    生产代码只接入这一条组合后的路径，不保留旧 RU 方法副本作为回退。
  - 不得新增 `LW_*` A/B 开关或“上游原版 + LW 版”双实现；需要短期诊断对照时必须由用户
    明确要求，并在验证完成后删除临时路径。
- 用户实例字段不写在上游 `__init__` 里——`CombatExtMixin.__init__` 会经由上游
  `super().__init__()` 链被调用, 用户字段统一在那里初始化。
- RU 改变异常或状态模型时，必须在同一交付中更新 `src/lw/` 的导入、捕获和状态处理，不保留
  已被 RU 删除的旧异常作为兼容层。LW 专属信号只有在表达与 RU 新模型不同的用户行为时才保留。
- 新增或修改 Python 源码中的注释和字符串时, 使用 ASCII `,` 和 `;`, 不使用全角 `，` 或 `；`,
  避免易混淆 Unicode 字符告警。

## 其他

- 用户 git 身份有两个,是同一人:`龙威 <376504041@qq.com>`、`longwei <longwei@mgtv.com>`。
- 每个独立功能/修复完成且相关测试通过后直接创建独立 Git 提交；只提交本功能范围，
  不夹带用户已有改动、本地配置或无关未跟踪文件。
- 运行测试:`.\run_tests.ps1`(或 `python -m pytest tests/ -x -q`)。
