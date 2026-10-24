"""Controller v2 board interface (laser switch) using the kat_board library."""

import logging
import threading
import time
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)

# Time to let the laser output stabilise after switching it on, before exposing
LASER_WARMUP_S = 0.5

# kat_board needs smbus2 + gpiozero/lgpio and the board itself, so it is only
# usable on a Raspberry Pi with the controller v2 board attached
try:
    from kat_board import BoardController
    KAT_BOARD_AVAILABLE = True
    logger.info("kat_board imported successfully")
except ImportError as e:
    KAT_BOARD_AVAILABLE = False
    logger.warning("kat_board not available: %s", e)


class LocalBoard:
    """
    Laser control through the KAT controller v2 board.

    The laser is driven by GPIO23 through a TPS2553 switch with a pull-down,
    so it is off whenever this process isn't holding it on.

    Example:
        >>> board = LocalBoard()
        >>> with board.laser_enabled():
        ...     jpeg_bytes = camera.capture_photo()
    """

    def __init__(self):
        """Initialize the board (heater and laser start off)."""
        self._board = BoardController()
        self._lock = threading.Lock()
        # Serialises laser_enabled() blocks so one capture can't switch the
        # laser off while another is still exposing
        self._session_lock = threading.Lock()

    def laser_on(self) -> None:
        """Switch the laser supply on."""
        with self._lock:
            logger.info("Laser on")
            self._board.laser.on()

    def laser_off(self) -> None:
        """Switch the laser supply off."""
        with self._lock:
            logger.info("Laser off")
            self._board.laser.off()

    def is_laser_on(self) -> bool:
        """Check if the laser supply is currently on."""
        with self._lock:
            return self._board.laser.enabled

    @contextmanager
    def laser_enabled(self, warmup_s: float = LASER_WARMUP_S) -> Iterator[None]:
        """Keep the laser on for the duration of the block, always switching it off after."""
        with self._session_lock:
            self.laser_on()
            try:
                time.sleep(warmup_s)
                yield
            finally:
                self.laser_off()

    def close(self) -> None:
        """Turn everything off and release the GPIO/I2C resources."""
        with self._lock:
            try:
                self._board.close()
            except Exception as e:
                logger.error("Error closing board: %s", e)

    def __enter__(self) -> "LocalBoard":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


# Mock board for development/testing without the controller board
class MockBoard:
    """Mock board for testing on systems without the controller v2 board."""

    def __init__(self):
        self._laser = False

    def laser_on(self) -> None:
        logger.info("Laser on (mock)")
        self._laser = True

    def laser_off(self) -> None:
        logger.info("Laser off (mock)")
        self._laser = False

    def is_laser_on(self) -> bool:
        return self._laser

    @contextmanager
    def laser_enabled(self, warmup_s: float = LASER_WARMUP_S) -> Iterator[None]:
        self.laser_on()
        try:
            yield
        finally:
            self.laser_off()

    def close(self) -> None:
        self._laser = False

    def __enter__(self) -> "MockBoard":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def get_board() -> "LocalBoard | MockBoard":
    """
    Get appropriate board instance based on platform.

    Returns LocalBoard when kat_board is installed and the board initialises,
    MockBoard otherwise (captures still work, just without laser control).
    """
    if KAT_BOARD_AVAILABLE:
        try:
            board = LocalBoard()
            logger.info("Created LocalBoard (controller v2 board)")
            return board
        except Exception as e:
            logger.warning("Controller board init failed, laser control disabled: %s", e)
    logger.info("Creating MockBoard (no laser control)")
    return MockBoard()
