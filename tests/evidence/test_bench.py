from telltale.bench.run import run_benchmark
from telltale.core.schema import VideoFacts
from telltale.logs.generate import ClipTiming


def test_benchmark_reports_accuracy_on_synthetic_timing(tmp_path):
    t = ClipTiming("syn", 4.0, 6.2)
    vf = VideoFacts("syn", 30.0, 4.0, 6.2, 1.9, "1")
    res = run_benchmark(n_seeds=1, timings=[(t, vf)], out=tmp_path / "bench.json")
    s = res["summary"]
    assert s["n"] == 12  # 2 profiles x 6 stories
    assert s["accuracy"] >= 0.8
    assert {"per_story", "confusion", "abstention_correct", "false_inconclusive"} <= set(s)
