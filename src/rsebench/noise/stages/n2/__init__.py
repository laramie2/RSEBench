"""N2 environment-evidence noise plugin boundary."""

from rsebench.noise.contracts import NoisePlugin

PLUGIN = NoisePlugin(
    stage="N2",
    form="static",
    entrypoint="rsebench.noise.stages.n2:PLUGIN",
    version="1",
    operators_root="rsebench.noise.stages.n2.operators",
)

__all__ = ["PLUGIN"]
