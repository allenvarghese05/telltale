import pytest

from telltale.logs.can_io import decode_signals, load_dbc, message_for_signal, read_candump, write_candump


@pytest.mark.parametrize("dbc", ["car.dbc", "truck.dbc"])
def test_roundtrip(tmp_path, dbc):
    db = load_dbc(dbc)
    ms = message_for_signal(db, "speed_mps")
    mb = message_for_signal(db, "brake_request")
    frames = [
        (1700000000.0, ms.frame_id, ms.encode({"speed_mps": 25.37}), ms.is_extended_frame),
        (1700000000.02, mb.frame_id, mb.encode({"brake_request": 1, "brake_pressure_kpa": 410}), mb.is_extended_frame),
    ]
    p = tmp_path / "x.log"
    write_candump(p, frames)
    sig = decode_signals(read_candump(p), db)
    assert sig["speed_mps"][1][0] == pytest.approx(25.37, abs=0.01)
    assert sig["brake_pressure_kpa"][1][0] == 410
    assert sig["brake_request"][0][0] == pytest.approx(1700000000.02, abs=1e-6)


def test_truck_ids_are_extended():
    assert message_for_signal(load_dbc("truck.dbc"), "speed_mps").is_extended_frame
