from __future__ import annotations

import pytest

from collector.settings import Config, load_config


@pytest.fixture(scope="session")
def cfg() -> Config:
    return load_config()
