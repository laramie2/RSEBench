from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_baseline_downloader_is_non_destructive_and_registry_driven():
    text = (ROOT / "scripts/download/baselines.sh").read_text()
    assert "methods.yaml" in text
    assert "git clone" in text
    assert "checkout --detach" in text
    assert "rm -rf" not in text
    assert "--no-checkout" not in text
