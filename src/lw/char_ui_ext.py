# [lw] CharUIMixin 的用户扩展: 大招菱形检测。
# 通过 class CharUIMixin(CharUIExtMixin, BaseTask) 接线(src/tasks/mixin/CharUIMixin.py), self 即任务实例。
# 注: 原 lw_stable_current_char"稳定判定放宽"已随上游更换当前角色检测算法
# (current_char_detector 的 active_marker + sticky tracker)退役, 上游 sticky 粘滞机制覆盖了同一需求。
import time
from typing import TYPE_CHECKING

import cv2

if TYPE_CHECKING:
    from ok import Box

    from src.tasks.BaseNTETask import BaseNTETask

    _TaskProxy = BaseNTETask
else:

    class _TaskProxy:
        pass


class CharUIExtMixin(_TaskProxy):
    # 下场(后台)角色头像右侧的"大招就绪菱形"格:有大招才亮菱形,前台角色无菱形。
    # 菱形下面还有个常驻圆形(技能图标),框千万别骑到圆形上,否则判的是"在不在后台"而非"有无大招"。
    # 用边缘能量(Laplacian 方差)判:≥PRESENT 算有大招;≤ABSENT 算没有;中间 None(回退原逻辑)。
    # 坐标实测自 2560x1440:扫描 lap 峰值定位 4 个菱形中心 y≈312/496/666/840,线性拟合=
    # 起点中心 312、竖直间距 176 → 32x32 框顶 ULT_DIAMOND_Y=296(中心-16),按 176 间距复制到各槽。
    # 实测(框居中菱形后):后台有大招 lap 2.8w~4.6w,后台无大招 ~4.5k,前台/空槽 <0.7k,
    # 8000~17000 几乎不出现(早期 12000~16500"快满"假象其实是框偏低 16px、骑到了下面的圆形上)。
    ULT_DIAMOND_X = 2440
    ULT_DIAMOND_Y = 296
    ULT_DIAMOND_SIZE = 32
    ULT_DIAMOND_LAP_PRESENT = 17000
    ULT_DIAMOND_LAP_ABSENT = 8000

    def lw_dump_char_slot_scores(self, threshold_floor=0.3):
        """诊断: 逐个头像槽位跑模板匹配, 返回每槽位跨对比度的最佳匹配分数(含未命中的)。

        正式识别 _multi_stage_char_match 阈值 0.7、命中即算该槽有人; 队伍人数抖动(少
        识别一人)时用它看缺失槽位的实际分数, 区分两种情况:
          - 擦边(0.6x): 头像还在但被大招演出/遮挡/画面变化瞬时压到阈值下 → 抖动误判, 不该 reload
          - 彻底没有(返回 0.0 = <threshold_floor): 头像真消失(倒地/离场) → 真减员
        参数与 _multi_stage_char_match 完全一致(mask/对比度档/horizontal_variance), 保证分数可比。
        只在检测到人数变化那一刻调一次(罕见), 4 槽×最多4档模板匹配的开销可接受。
        """
        from src.utils import image_utils as iu

        scores = []
        for i in range(4):
            best = 0.0
            for c_val in (0, 30, 60, 90):

                def process(image, current_c=c_val):
                    return iu.adjust_lightness_contrast_lab(image, brightness=0, contrast=current_c)

                res = self.find_one(
                    f"char_{i + 1}_text",
                    threshold=threshold_floor,
                    frame_processor=process,
                    mask_function=iu.mask_outside_white_rect,
                    horizontal_variance=0.005,
                )
                if res and res.confidence > best:
                    best = res.confidence
            scores.append(best)
        return scores

    def get_ultimate_diamond_box(self, index: int) -> "Box":
        """第 index 个角色头像右侧"大招就绪菱形"格的区域框(随分辨率缩放、跟 UI 偏移)。"""
        box = self.box_of_screen_scaled(
            2560,
            1440,
            self.ULT_DIAMOND_X,
            self.ULT_DIAMOND_Y,
            width_original=self.ULT_DIAMOND_SIZE,
            height_original=self.ULT_DIAMOND_SIZE,
        )
        if self._char_ui_offset:
            box = self._shift_char_ui_box(box)
        return self.get_box_by_char_spacing(box, index)

    def off_field_ultimate_ready(self, index: int, frame=None):
        """看下场角色头像的元素菱形是否亮起 => 大招就绪。

        菱形是硬描边几何图标(高边缘能量),没大招时该格是空背景/头像光晕(平滑、低边缘能量),
        用 Laplacian 方差区分,属性无关、亮/暗背景通吃。返回 True(就绪)/ False(未就绪)/
        None(介于阈值之间不确定,或裁帧失败 —— 调用方回退到原时间推算)。
        """
        try:
            if frame is None:
                frame = self.frame
            if frame is None:
                return None
            crop = self.get_ultimate_diamond_box(index).crop_frame(frame)
            if crop is None or crop.size == 0:
                return None
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            lap_var = float(cv2.Laplacian(gray, cv2.CV_64F, ksize=3).var())
            if lap_var >= self.ULT_DIAMOND_LAP_PRESENT:
                result = True
            elif lap_var <= self.ULT_DIAMOND_LAP_ABSENT:
                result = False
            else:
                result = None
            # 诊断日志:每角色每秒最多一条,便于验证识别准度/调阈值
            log_times = getattr(self, "_ult_diamond_log_times", None)
            if log_times is None:
                log_times = {}
                self._ult_diamond_log_times = log_times
            now = time.time()
            if now - log_times.get(index, 0) > 1.0:
                log_times[index] = now
                self.log_info(f"ult diamond char{index + 1} lap={lap_var:.0f} -> {result}")
            return result
        except Exception as e:
            self.log_debug(f"off_field_ultimate_ready failed: {e}")
            return None
