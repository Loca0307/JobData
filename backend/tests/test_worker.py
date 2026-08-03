import logging

from app.workers.scrape_all import configure_logging


def test_worker_logging_supplies_context_defaults(monkeypatch):
    captured: dict[str, object] = {}

    def fake_basic_config(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(logging, "basicConfig", fake_basic_config)

    configure_logging()

    handlers = captured["handlers"]
    assert isinstance(handlers, list)
    formatter = handlers[0].formatter
    assert formatter is not None
    output = formatter.format(logging.LogRecord(
        name="worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="started",
        args=(),
        exc_info=None,
    ))
    assert "run_id=- source=- started" in output
