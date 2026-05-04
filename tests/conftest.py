import pytest

# pytest-asyncio のデフォルトモードを auto に設定
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
