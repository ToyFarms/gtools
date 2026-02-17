from dataclasses import dataclass
import numpy as np
import numpy.typing as npt
from pyglm.glm import vec4


@dataclass(slots=True)
class RenderCommand:
    buffer: npt.NDArray[np.uint8]
    dst: list[vec4]
