from telltale.data.fetch import format_positive_clips, parse_positive_rows

ROWS = [
    {
        "file_name": "00822.mp4",
        "time_of_event": "19.5",
        "time_of_alert": "18.633",
        "light_conditions": "Normal",
        "weather": "Cloudy",
        "scene": "Urban",
    },
    {
        "file_name": "00072.mp4",
        "time_of_event": "20.101",
        "time_of_alert": "",
        "light_conditions": "Normal",
        "weather": "Clear",
        "scene": "Urban",
    },
    {"file_name": "01924.mp4", "time_of_event": "", "time_of_alert": "", "weather": "Clear"},
]


def test_parse_skips_rows_without_an_event_time():
    assert [c["nexar_id"] for c in parse_positive_rows(ROWS)] == ["00822", "00072"]


def test_parse_reads_times_and_conditions():
    first = parse_positive_rows(ROWS)[0]
    assert first == {
        "nexar_id": "00822",
        "time_of_event": 19.5,
        "time_of_alert": 18.633,
        "scene": "Urban",
        "weather": "Cloudy",
        "light": "Normal",
    }


def test_parse_leaves_a_missing_alert_time_as_none():
    assert parse_positive_rows(ROWS)[1]["time_of_alert"] is None


def test_format_lines_are_one_per_clip_and_tab_separated():
    lines = format_positive_clips(parse_positive_rows(ROWS))
    assert len(lines) == 2
    assert lines[0].split("\t") == ["00822", "event=19.50s", "alert=18.63s", "Urban", "Cloudy", "Normal"]
    assert lines[1].split("\t")[2] == "alert=none"
