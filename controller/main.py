"""
Simulato Main Control PC entry point.

Starts the FastAPI server and initializes the system controller.
This is the single entry point for the PC side of the Simulato system.

Usage:
    python -m controller.main
"""

import threading
import uvicorn

from controller.config import (
    CONTROLLER_HOST,
    CONTROLLER_PORT,
    LOCAL_AI_ASSIST_ENABLED,
    OLLAMA_API_URL,
    OLLAMA_MODEL,
    OLLAMA_KEEP_ALIVE,
)
from controller.orchestrator.system_controller import SystemController
from controller.mobile_api.api_server import (
    app,
    set_command_callback,
    set_image_callback,
    set_stream_frame_callback,
    set_decision_callback,
    set_status_provider,
    set_disconnection_callback,
)
from controller.utils.logger import get_logger

logger = get_logger("main")


def warmup_ollama() -> None:
    """
    Pre-load the Ollama model into GPU memory by sending a
    lightweight warmup request. This eliminates the 10-30 second
    cold start delay on the first real image processing call.

    Runs in a background thread so it doesn't block server startup.
    """
    if not LOCAL_AI_ASSIST_ENABLED:
        logger.info("Local AI assist disabled — skipping model warmup")
        return

    def _warmup():
        import requests
        logger.info("Warming up local AI model: %s", OLLAMA_MODEL)
        try:
            payload = {
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
                "keep_alive": OLLAMA_KEEP_ALIVE,
            }
            resp = requests.post(OLLAMA_API_URL, json=payload, timeout=120)
            resp.raise_for_status()
            logger.info("Local AI model loaded into GPU successfully")
        except requests.exceptions.ConnectionError:
            logger.warning(
                "Ollama server not reachable at %s. "
                "Local AI features will be unavailable until Ollama is running.",
                OLLAMA_API_URL,
            )
        except Exception as e:
            logger.warning("Ollama warmup failed: %s", e)

    thread = threading.Thread(target=_warmup, daemon=True, name="ollama-warmup")
    thread.start()


def main() -> None:
    logger.info("=" * 60)
    logger.info("SIMULATO CONTROLLER — Starting")
    logger.info("=" * 60)

    # Pre-load local AI model into GPU (background thread)
    warmup_ollama()

    controller = SystemController()
    if not controller.connect_pi():
        logger.warning("Pi not connected at startup; click commands will fail until Pi listener is reachable")

    set_command_callback(controller.handle_command)
    set_image_callback(controller.on_image_received)
    set_stream_frame_callback(controller.on_stream_frame_received)
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
            access_log=False,
        )
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        controller.shutdown()
        logger.info("SIMULATO CONTROLLER — Stopped")


if __name__ == "__main__":
    main()

