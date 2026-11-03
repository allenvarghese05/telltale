"""Command-line entry point. All commands are wired here; implementations are imported lazily per command."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2))


def _fetch_list(_: argparse.Namespace) -> None:
    from telltale.data.fetch import print_positive_clips

    print_positive_clips()


def _fetch(a: argparse.Namespace) -> None:
    from telltale.data.fetch import fetch_clip

    _print_json(fetch_clip(a.nexar_id, a.clip_id))


def _add_clip(a: argparse.Namespace) -> None:
    from telltale.data.fetch import add_clip

    _print_json(add_clip(a.path, a.clip_id, a.event_time))


def _lane_preview(a: argparse.Namespace) -> None:
    from telltale.video.preview import lane_preview

    print(lane_preview(a.clip_id))


def _sam(a: argparse.Namespace) -> None:
    from telltale.video.sam import run_sam_for_clip

    print(run_sam_for_clip(a.clip_id))


def _witness(a: argparse.Namespace) -> None:
    from telltale.video.witness import run_witness_for_clip

    _print_json(run_witness_for_clip(a.clip_id))


def _video_report(a: argparse.Namespace) -> None:
    from telltale.video.report import video_report

    _print_json(video_report(a.clip_id))


def _video_bench(a: argparse.Namespace) -> None:
    from telltale.video.bench import run_video_bench

    _print_json(run_video_bench(a.n)["summary"])


def _generate(a: argparse.Namespace) -> None:
    from telltale.pipeline.demo import generate_for_clip

    print(generate_for_clip(a.clip_id, a.profile, a.story, a.seed))


def _make_demo(_: argparse.Namespace) -> None:
    from telltale.pipeline.demo import make_demo

    _print_json(make_demo())


def _analyze(a: argparse.Namespace) -> None:
    from telltale.pipeline.analyze import analyze

    bundle = analyze(a.case_id, live=a.live)
    print(bundle["verdict"]["agent_label"], bundle["verdict"]["status"], bundle["counts"])


def _analyze_all(a: argparse.Namespace) -> None:
    from telltale.pipeline.analyze import analyze_all

    for line in analyze_all(live=a.live):
        print(line)


def _benchmark(a: argparse.Namespace) -> None:
    from telltale.bench.run import run_benchmark

    _print_json(run_benchmark(n_seeds=a.seeds)["summary"])


def _agent_bench(a: argparse.Namespace) -> None:
    from telltale.pipeline.agent_bench import run_agent_bench

    _print_json(run_agent_bench(a.n)["summary"])


def _export_site(_: argparse.Namespace) -> None:
    from telltale.web.export import export_site

    print(export_site())


def _serve(a: argparse.Namespace) -> None:
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    from telltale.config import ROOT

    site = ROOT / "site"
    if not (site / "index.html").exists():
        raise SystemExit("No site built yet: run `telltale export-site` first.")
    handler = partial(SimpleHTTPRequestHandler, directory=str(site))
    print(f"Serving {site} at http://127.0.0.1:{a.port}")
    ThreadingHTTPServer(("127.0.0.1", a.port), handler).serve_forever()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="telltale", description="Meta AI investigates; the checker verifies.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add(name: str, handler: Callable[[argparse.Namespace], None], help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(handler=handler)
        return p

    add("fetch-list", _fetch_list, "list Nexar crash clips with labels")
    p = add("fetch", _fetch, "download and trim one Nexar clip")
    p.add_argument("nexar_id")
    p.add_argument("--clip-id", required=True)
    p = add("add-clip", _add_clip, "register your own dashcam clip")
    p.add_argument("path")
    p.add_argument("--clip-id", required=True)
    p.add_argument("--event-time", type=float, required=True)
    p = add("lane-preview", _lane_preview, "draw the ego-lane polygon on a frame")
    p.add_argument("clip_id")
    p = add("sam", _sam, "track vehicles with SAM 3.1")
    p.add_argument("clip_id")
    p = add("witness", _witness, "Muse Spark video witness")
    p.add_argument("clip_id")
    p = add("video-report", _video_report, "video-only timeline for any clip")
    p.add_argument("clip_id")
    p = add("video-bench", _video_bench, "benchmark against Nexar human labels")
    p.add_argument("--n", type=int, default=40)
    p = add("generate", _generate, "generate one vehicle-log case")
    p.add_argument("clip_id")
    p.add_argument("--profile", default="car")
    p.add_argument("--story", required=True)
    p.add_argument("--seed", type=int, default=1)
    add("make-demo", _make_demo, "generate the demo cases")
    p = add("analyze", _analyze, "investigate and verify one case")
    p.add_argument("case_id")
    p.add_argument("--live", action="store_true")
    p = add("analyze-all", _analyze_all, "investigate and verify every case")
    p.add_argument("--live", action="store_true")
    p = add("benchmark", _benchmark, "synthetic blind attribution benchmark")
    p.add_argument("--seeds", type=int, default=4)
    p = add("agent-bench", _agent_bench, "agent alone vs agent + checker")
    p.add_argument("--n", type=int, default=18)
    add("export-site", _export_site, "build the static replay site into site/")
    p = add("serve", _serve, "serve the built site locally")
    p.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.handler(args)


if __name__ == "__main__":
    main()
