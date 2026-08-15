import unittest
from unittest import mock

from ok import Box

from src.lw.nte_task_ext import NTETaskExtMixin
from src.tasks.BaseNTETask import BaseNTETask


class TestFindConfirm(unittest.TestCase):
    def test_lw_confirm_forwards_the_current_mask_contract_to_each_template_search(self):
        task = object.__new__(NTETaskExtMixin)
        task.main_viewport = object()
        task.find_feature = mock.Mock(return_value=[])
        mask_function = object()

        self.assertIsNone(task.lw_find_confirm(mask_function=mask_function))

        self.assertEqual(task.find_feature.call_count, 2)
        for call in task.find_feature.call_args_list:
            self.assertIs(call.kwargs["mask_function"], mask_function)

    def test_current_wait_click_confirm_clicks_the_detected_confirmation(self):
        task = object.__new__(BaseNTETask)
        button = object()
        on_found = mock.Mock()
        task.find_confirm = mock.Mock(side_effect=[button, None])
        task.operate_click = mock.Mock()
        task.sleep = mock.Mock()

        def wait_until(condition, **kwargs):
            if pre_action := kwargs.get("pre_action"):
                pre_action()
            return condition()

        task.wait_until = mock.Mock(side_effect=wait_until)

        self.assertTrue(
            BaseNTETask.wait_click_confirm(
                task,
                range=Box(0, 0, 10, 10, name="confirm_area"),
                on_found=on_found,
            )
        )

        on_found.assert_called_once_with()
        task.operate_click.assert_called_once_with(button, interval=1)


if __name__ == "__main__":
    unittest.main()
