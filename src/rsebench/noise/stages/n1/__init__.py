"""N1 task-context noise plugin boundary."""

from rsebench.noise.contracts import NoisePlugin

PLUGIN = NoisePlugin(
    stage="N1",
    form="static",
    entrypoint="rsebench.noise.stages.n1:PLUGIN",
    version="1",
    operators_root="rsebench.noise.stages.n1.operators",
)

__all__ = ["PLUGIN"]
