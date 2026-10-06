import pytest

from evidenceloop.tasks.generator import generate_split


@pytest.fixture(scope="session")
def calibration():
    pubs, privs, rejects = generate_split("calibration", 30)
    return pubs, {p["task_id"]: p for p in privs}, rejects


@pytest.fixture(scope="session")
def validation_pool():
    pubs, privs, _ = generate_split("validation", 60)
    return pubs, {p["task_id"]: p for p in privs}


@pytest.fixture(scope="session")
def ood_pool():
    pubs, privs, rejects = generate_split("test_ood", 60)
    return pubs, {p["task_id"]: p for p in privs}, rejects
