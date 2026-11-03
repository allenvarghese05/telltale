"""ADAS log I/O: JSON-encoded messages in an MCAP container, the format real AV stacks record."""

from __future__ import annotations

import json

from mcap.reader import make_reader
from mcap.writer import Writer


def write_adas_mcap(path, messages) -> None:
    """messages: iterable of (topic, log_time_ns, payload_dict)."""
    with open(path, "wb") as f:
        w = Writer(f)
        w.start()
        sid = w.register_schema(name="telltale.Json", encoding="jsonschema", data=b'{"type":"object"}')
        channels: dict[str, int] = {}
        for topic, t_ns, payload in sorted(messages, key=lambda m: m[1]):
            if topic not in channels:
                channels[topic] = w.register_channel(topic=topic, message_encoding="json", schema_id=sid)
            w.add_message(
                channel_id=channels[topic],
                log_time=int(t_ns),
                publish_time=int(t_ns),
                data=json.dumps(payload).encode(),
            )
        w.finish()


def read_adas_mcap(path) -> dict[str, list[tuple[float, dict]]]:
    """Read an ADAS MCAP into {topic: [(log_time_s, payload), ...]} in log order."""
    out: dict[str, list[tuple[float, dict]]] = {}
    with open(path, "rb") as f:
        for _schema, channel, message in make_reader(f).iter_messages():
            out.setdefault(channel.topic, []).append((message.log_time / 1e9, json.loads(message.data)))
    return out
