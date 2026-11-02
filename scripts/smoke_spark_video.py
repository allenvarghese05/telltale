"""Smoke test: does Muse Spark accept a video and answer about it?

Usage: python scripts/smoke_spark_video.py path/to/clip.mp4
"""

import sys
from pathlib import Path

from telltale.config import WITNESS_MODEL, client

QUESTION = "Does another vehicle change into the camera car's lane? Give the approximate time in seconds."


def main() -> None:
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_file():
        sys.exit("usage: python scripts/smoke_spark_video.py path/to/clip.mp4")
    api = client()
    with open(sys.argv[1], "rb") as fh:
        uploaded = api.files.create(file=fh, purpose="user_data")
    response = api.responses.create(
        model=WITNESS_MODEL,
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": QUESTION},
                    {"type": "input_file", "file_id": uploaded.id},
                ],
            }
        ],
    )
    print(response.output_text)


if __name__ == "__main__":
    main()
