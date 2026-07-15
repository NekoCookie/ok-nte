import unittest
from src.config import config
from ok.test.TaskTestCase import TaskTestCase
from src.tasks.trigger.AutoCombatTask import AutoCombatTask

config['debug'] = True


class TestCD(TaskTestCase):
    task_class = AutoCombatTask
    config = config

    def test_cd1(self):
        self.task.do_reset_to_false()
        self.set_image('tests/images/01.png')
        self.task.load_chars()
        self.assertTrue(self.task.has_cd('ultimate'))
        self.assertTrue(self.task.has_cd('skill'))

    def test_cd2(self):
        self.task.do_reset_to_false()
        self.set_image('tests/images/02.png')
        self.task.load_chars()
        # [lw] 图中 Q 大招位是未充能空圈(无亮图标、无CD数字)。lw CD锚定语义: 读不到数字且
        # 图标不亮 → 保守当冷却中(防误判可用→空按)。上游原断言 False("无数字=无冷却"),
        # lw 语义下应为 True; 大招一充能图标亮起, refresh_cd 当帧即锚 0, 不会拖住真就绪。
        self.assertTrue(self.task.has_cd('ultimate'))  # [lw] 原为 assertFalse
        self.assertFalse(self.task.has_cd('skill'))  # E 技能图标亮白=就绪, 继续守护这条

if __name__ == '__main__':
    unittest.main()
