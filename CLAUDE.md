# 仓库约定(必读)

本仓库 fork 自上游 ru(BnanZ0/ok-nte, remote 名 `upstream`),用户(龙威/longwei)的改动
遵循以下解耦约定,目的是把与上游的合并冲突面压到最小。**任何时候修改代码都必须遵守。**

## 用户代码放哪

- **`src/lw/` 是用户专属包**,所有整块新增的方法/常量/类一律放这里,通过 Mixin 接入上游类:
  - `combat_ext.py` → `CombatExtMixin`,接入 `BaseCombatTask`(CD锚定、角色不可用、队伍变更检测、trigger重载等)
  - `char_ext.py` → `CharExtMixin`,接入 `BaseChar`(技能结算、大招 settle、空闲平A等)
  - `char_ui_ext.py` → `CharUIExtMixin`,接入 `CharUIMixin`(位于 `src/tasks/mixin/CharUIMixin.py`,大招菱形检测等)
  - `combat_templates.py` → LW 主C、公共资源辅助、增益辅助、治疗和早雾辅助模板
  - `nte_task_ext.py` → `NTETaskExtMixin`,接入 `BaseNTETask`(find_confirm OCR认字等)
  - `sound_ext.py` → `SoundContextExtMixin`,接入 `SoundCombatContext`
  - `chars.py` → 用户角色注册表(`CharFactory.char_dict.update(lw_char_dict)`)
- 用户自有的完整文件(如 `src/char/Requiem.py`、`src/combat/requiem_combo.py`、
  `src/tasks/trigger/NanallySuperJumpTask.py`)不受此限,它们本身不与上游冲突。

战斗出招和切换已经统一迁移到 RU planner；旧 `do_perform`、旧 `Priority/Role` 和
planner A/B 总开关已经退役，不再新增兼容分支。

## 智能体约定同步

- `CLAUDE.md` 是 Claude 的项目指令，`AGENTS.md` 是 Codex 的项目指令；两者共享的仓库约定必须保持同步。
- 修改任一文件中的共享约定时，必须同时检查并更新另一文件，避免 Claude 与 Codex 执行标准不一致。
- 仅适用于某一工具的专属指令应明确标注适用对象，无需机械复制到另一文件。

## `# [lw]` 标记

上游源文件里**凡带 `# [lw]` 注释的行/块都是用户改动**:
- 合并上游时这些行**必须保留**(冲突时以本地为准,再人工比对上游对同一处的新改动)。
- 带 `[lw] 本方法被大幅改写` 的方法(如 `BaseCombatTask.refresh_cd`/`load_chars`)整体属于用户,
  合并冲突时以本地版本为准,然后人工检查上游对该方法的改动是否需要吸收。
- 给上游文件新增用户逻辑时:能放 `src/lw/` 就放(上游文件只留一行接线),必须留在原地的
  改动压到最短并加 `# [lw]` 标记。**不要**在上游文件里写成片的用户代码。

## 技术限制

- Mixin 作为基类**不能 override** 上游类体里已定义的方法(Python MRO 子类优先)。
  要改上游方法的行为:
  - **小改动**(几行以内): 就地改 + `# [lw]` 标记;
  - **整方法改写**: 用"开关分发"模式——上游方法体顶部加两行 `[lw]` 分发,
    实现放 `src/lw/` 里的 `lw_<方法名>`,开关是 `CombatExtMixin` 等上的 `LW_*` 类常量(默认 True);
    上游原版方法体**原样保留**在分发之后,作对照/排查回退用。现有例子:
    `BaseCombatTask.refresh_cd`(`LW_CD_ANCHORING` → `lw_refresh_cd`)、
    `BaseCombatTask.load_chars`(`LW_LOAD_CHARS` → `lw_load_chars`)、
    `AutoCombatTask.run`(`LW_COMBAT_RUN` → `lw_combat_run`)。
- 用户实例字段不写在上游 `__init__` 里——`CombatExtMixin.__init__` 会经由上游
  `super().__init__()` 链被调用, 用户字段统一在那里初始化。
    合并上游时: 分发两行保留;上游对原版方法体的改动正常合入(它是原版对照),
    合完后人工比对上游改了什么、决定是否吸收进 `lw_` 版。
- `CharUnavailableException`/`TeamChangedException` 定义在 `BaseCombatTask.py`(继承
  NotInCombatException 会循环 import),`src/lw/` 内引用它们用方法内局部 import。

## 其他

- 用户 git 身份有两个,是同一人:`龙威 <376504041@qq.com>`、`longwei <longwei@mgtv.com>`。
- 每个独立功能/修复完成且相关测试通过后直接创建独立 Git 提交；只提交本功能范围，
  不夹带用户已有改动、本地配置或无关未跟踪文件。
- 运行测试:`.\run_tests.ps1`(或 `python -m pytest tests/ -x -q`)。
