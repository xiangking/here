from core.delivery import DeliveryCapabilityProbe
from core.delivery.messaging import MessagingConfig


def test_probe_keeps_desktop_available_when_external_config_missing(monkeypatch):
    monkeypatch.setattr(MessagingConfig, "auto_load", classmethod(lambda cls: MessagingConfig({})))
    caps = DeliveryCapabilityProbe().probe()

    assert caps["desktop_chat"].available is True
    assert caps["telegram"].available is False
    assert caps["telegram"].reason == "missing_config:token"


def test_probe_marks_configured_channel_available(monkeypatch):
    monkeypatch.setattr(
        MessagingConfig,
        "auto_load",
        classmethod(lambda cls: MessagingConfig({"telegram": {"enabled": True, "token": "t", "target": "123"}})),
    )
    caps = DeliveryCapabilityProbe().probe()

    assert caps["telegram"].supported is True
    assert caps["telegram"].configured is True
    assert caps["telegram"].available is True
    assert caps["discord"].available is False


def test_probe_does_not_treat_empty_target_as_configured(monkeypatch):
    monkeypatch.setattr(
        MessagingConfig,
        "auto_load",
        classmethod(lambda cls: MessagingConfig({"telegram": {"enabled": True, "token": "t", "target": ""}})),
    )
    caps = DeliveryCapabilityProbe().probe()

    assert caps["telegram"].supported is True
    assert caps["telegram"].configured is False
    assert caps["telegram"].available is False
    assert caps["telegram"].reason == "missing_target"
