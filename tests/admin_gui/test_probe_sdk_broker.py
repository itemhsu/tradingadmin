"""SDK 券商（如永豐 sinopac）：probe_broker 應略過 REST 測試、直接視為通過。"""
from admin_gui.services import probes


def test_sdk_broker_skips_rest_and_passes():
    spec = {"integration": {"type": "sdk"},
            "environments": {"paper": {"simulation": True}}}  # 無 base_url
    ok, msg = probes.probe_broker(spec, "paper", "key", "secret")
    assert ok is True
    assert "略過" in msg or "SDK" in msg


def test_rest_broker_still_requires_base_url():
    spec = {"integration": {"type": "rest"},
            "environments": {"paper": {}}}  # 無 base_url → REST 應報錯
    ok, msg = probes.probe_broker(spec, "paper", "key", "secret")
    assert ok is False
    assert "base_url" in msg
