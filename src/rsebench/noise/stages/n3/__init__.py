"""N3 trajectory-evidence noise plugin boundary."""

from rsebench.noise.contracts import NoisePlugin

PLUGIN = NoisePlugin(
    stage="N3",
    form="runtime",
    entrypoint="rsebench.noise.stages.n3:PLUGIN",
    version="1",
    operators_root="rsebench.noise.stages.n3.operators",
)

__all__ = ["PLUGIN"]
