import pytest

from telltale.cli import build_parser

COMMANDS = [
    ["fetch-list"],
    ["fetch", "00822", "--clip-id", "nx01"],
    ["add-clip", "clip.mp4", "--clip-id", "mine", "--event-time", "7.4"],
    ["lane-preview", "nx01"],
    ["sam", "nx01"],
    ["witness", "nx01"],
    ["video-report", "nx01"],
    ["video-bench", "--n", "5"],
    ["generate", "nx01", "--story", "brake_slow"],
    ["make-demo"],
    ["analyze", "nx01-car-s0101", "--live"],
    ["analyze-all"],
    ["benchmark", "--seeds", "2"],
    ["agent-bench", "--n", "3"],
    ["export-site"],
    ["serve", "--port", "9000"],
]


@pytest.mark.parametrize("argv", COMMANDS, ids=lambda a: a[0])
def test_every_planned_command_parses_and_has_a_handler(argv):
    args = build_parser().parse_args(argv)
    assert callable(args.handler)


def test_unknown_command_is_rejected():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["delete-everything"])
