import os
import sys
import unittest

_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from fastapi.responses import JSONResponse

from core.api_handler import _derive_state, _response_error_message


class ApiErrorLoggingTests(unittest.TestCase):
    def test_http_400_message_is_logged(self):
        response = JSONResponse(
            {"state": "error", "message": "具体连接错误"},
            status_code=400,
        )
        self.assertEqual(_derive_state(response, None), "error")
        self.assertEqual(_response_error_message(response), "具体连接错误")

    def test_error_dict_is_not_misclassified_as_success(self):
        response = {"state": "error", "message": "参数错误"}
        self.assertEqual(_derive_state(response, None), "error")
        self.assertEqual(_response_error_message(response), "参数错误")

    def test_success_response_has_no_error_message(self):
        response = {"state": "success", "data": {"ok": True}}
        self.assertEqual(_derive_state(response, None), "success")
        self.assertIsNone(_response_error_message(response))


if __name__ == "__main__":
    unittest.main()
