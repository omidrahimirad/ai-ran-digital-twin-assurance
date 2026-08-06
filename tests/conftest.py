from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from ai_ran_assurance.api.main import STATE, app
from ai_ran_assurance.config import ProjectConfig, load_config
from ai_ran_assurance.workflow import ClosedLoopEngine


@pytest.fixture(scope="session")
def project_config() -> ProjectConfig:
    return load_config()


@pytest.fixture(scope="session")
def closed_loop(project_config: ProjectConfig) -> ClosedLoopEngine:
    return ClosedLoopEngine(project_config)


@pytest.fixture()
def client(closed_loop: ClosedLoopEngine) -> Iterator[TestClient]:
    STATE.engine = closed_loop
    STATE.latest = None
    with TestClient(app) as test_client:
        yield test_client
