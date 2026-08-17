"""N4 feedback-evidence noise plugin boundary."""

from rsebench.noise.contracts import NoisePlugin

PLUGIN = NoisePlugin(
    stage="N4",
    form="runtime",
    entrypoint="rsebench.noise.stages.n4:PLUGIN",
    version="1",
    operators_root="rsebench.noise.stages.n4.operators",
)

__all__ = ["PLUGIN"]
