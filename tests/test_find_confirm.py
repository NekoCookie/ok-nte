import unittest
from unittest import mock

from src.lw.nte_task_ext import NTETaskExtMixin


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


if __name__ == "__main__":
    unittest.main()
