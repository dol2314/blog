import pytest

from autoposter import config


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    """설정·브라우저 프로필이 실제 홈 폴더 대신 임시 폴더에 저장되게 한다."""
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "PROFILES_DIR", tmp_path / "profiles")
    return tmp_path
