# [lw] 全面升级到 ru planner 架构的总开关(A/B 整体验证用)。
#
# False = 全队现状: 出招走各角色 do_perform + 切换走 lw_decide_switch_to(legacy Priority)。
# True  = 全队 planner: 出招走各角色 combat_plan + 切换走 planner.decide_switch。
#
# 为什么用一个总开关而非逐角色开关:
#   "planner 出招 + lw 切换"或"部分角色 planner、部分 do_perform"是从未设计过的混合态,
#   手感变化无法干净归因。逐角色迁移期间, 每个角色的 combat_plan 都写好并接此开关, 但
#   开关保持 False(现状零变化); 全部角色迁完后一次性切 True, 用"全 lw 打一场 vs 全 planner
#   打一场"整体对比。手感偏差集中在 planner 评分这一层(动作执行体复用原逻辑, 不变), 统一调。
#
# 迁移完成、planner 版手感验证等价后, 此开关可默认 True, do_perform/lw_decide_switch_to
# 作为回退保留(或退役)。
USE_PLANNER = False
