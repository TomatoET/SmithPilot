from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from main import check_visa_backend


class MainTests(unittest.TestCase):
    def test_visa_backend_check_opens_and_closes_py_backend(self) -> None:
        events: list[str] = []

        class FakeResourceManager:
            def close(self) -> None:
                events.append("close")

        fake_pyvisa = SimpleNamespace(
            ResourceManager=lambda backend: (
                events.append(backend),
                FakeResourceManager(),
            )[1]
        )

        with patch.dict(sys.modules, {"pyvisa": fake_pyvisa}):
            result = check_visa_backend()

        self.assertEqual(result, 0)
        self.assertEqual(events, ["@py", "close"])


if __name__ == "__main__":
    unittest.main()
