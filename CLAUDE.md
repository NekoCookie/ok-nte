# 仓库约定(必读)

本仓库 fork 自上游 ru(BnanZ0/ok-nte, remote 名 `upstream`),用户(龙威/longwei)的改动
遵循以下解耦约定,目的是把与上游的合并冲突面压到最小。**任何时候修改代码都必须遵守。**

## 用户代码放哪

- **`src/lw/` 是用户专属包**,所有整块新增的方法/常量/类一律放这里,通过 Mixin 接入上游类:
  - `combat_ext.py` → `CombatExtMixin`,接入 `BaseCombatTask`(CD锚定、角色不可用、队伍变更检测、trigger重载等)
  - `char_ext.py` → `CharExtMixin`,接入 `BaseChar`(技能结算、大招settle、空闲平A等)
  - `char_ui_ext.py` → `CharUIExtMixin`,接入 `CharUIMixin`(大招菱形检测等)
  - `nte_task_ext.py` → `NTETaskExtMixin`,接入 `BaseNTETask`(find_confirm OCR认字等)
  - `sound_ext.py` → `SoundContextExtMixin`,接入 `SoundCombatContext`
  - `chars.py` → 用户角色注册表(`CharFactory.char_dict.update(lw_char_dict)`)
- 用户自有的完整文件(如 `src/char/Requiem.py`、`src/char/MainDps.py`、`src/combat/requiem_combo.py`、
  `src/tasks/trigger/NanallySuperJumpTask.py`)不受此限,它们本身不与上游冲突。

## `# [lw]` 标记

上游源文件里**凡带 `# [lw]` 注释的行/块都是用户改动**:
- 合并上游时这些行**必须保留**(冲突时以本地为准,再人工比对上游对同一处的新改动)。
- 带 `[lw] 本方法被大幅改写` 的方法(如 `BaseCombatTask.refresh_cd`/`load_chars`)整体属于用户,
  合并冲突时以本地版本为准,然后人工检查上游对该方法的改动是否需要吸收。
- 给上游文件新增用户逻辑时:能放 `src/lw/` 就放(上游文件只留一行接线),必须留在原地的
  改动压到最短并加 `# [lw]` 标记。**不要**在上游文件里写成片的用户代码。

## 技术限制

- Mixin 作为基类**不能 override** 上游类体里已定义的方法(Python MRO 子类优先)。
  要改上游方法的行为:小改动就地改+标记;整方法改写就地改+方法顶标记。
- `CharUnavailableException`/`TeamChangedException` 定义在 `BaseCombatTask.py`(继承
  NotInCombatException 会循环 import),`src/lw/` 内引用它们用方法内局部 import。

## 其他

- 用户 git 身份有两个,是同一人:`龙威 <376504041@qq.com>`、`longwei <longwei@mgtv.com>`。
- 运行测试:`.\run_tests.ps1`(或 `python -m pytest tests/ -x -q`)。
