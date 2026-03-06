from .base import GamePlugin
from .checkers import CheckersPlugin
from .el_grande import ElGrandePlugin

REGISTRY: dict[str, type[GamePlugin]] = {
    "checkers": CheckersPlugin,
    "elgrande": ElGrandePlugin,
}
