"""
Simulato Main Control PC entry point.

Starts the FastAPI server and initializes the system controller.
This is the single entry point for the PC side of the Simulato system.

Usage:
    python -m controller.main
"""

import uvicorn

from controller.config import CONTROLLER_HOST, CONTROLLER_PORT
from controller.orchestrator.system_controller import SystemController
from controller.mobile_api.api_server import (
    app,
    set_command_callback,
    set_image_callback,
    set_decision_callback,
    set_status_provider,
    set_disconnection_callback,
)
from controller.utils.logger import get_logger

logger = get_logger("main")


def main() -> None:
    logger.info("=" * 60)
    logger.info("SIMULATO CONTROLLER — Starting")
    logger.info("=" * 60)

    controller = SystemController()

    set_command_callback(controller.handle_command)
    set_image_callback(controller.on_image_received)
    set_decision_callback(controller.handle_operator_decision)
    set_status_provider(controller.get_status)
    set_disconnection_callback(controller.on_device_disconnected)

    logger.info(
        "Starting API server on %s:%d",
        CONTROLLER_HOST, CONTROLLER_PORT,
    )

    try:
        uvicorn.run(
            app,
            host=CONTROLLER_HOST,
            port=CONTROLLER_PORT,
            log_level="info",
        )
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        controller.shutdown()
        logger.info("SIMULATO CONTROLLER — Stopped")


if __name__ == "__main__":
    main()
