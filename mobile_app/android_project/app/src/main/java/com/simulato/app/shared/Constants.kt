package com.simulato.app.shared

object Constants {
    const val HEARTBEAT_INTERVAL_MS = 5000L
    const val COMMAND_TIMEOUT_MS = 3000L
    const val IMAGE_UPLOAD_TIMEOUT_MS = 10000L
    const val RECONNECT_DELAY_MS = 3000L
    const val MAX_RETRIES = 3

    object MessageTypes {
        const val DEVICE_REGISTER = "DEVICE_REGISTER"
        const val REGISTER_ACK = "REGISTER_ACK"
        const val HEARTBEAT = "HEARTBEAT"
        const val HEARTBEAT_ACK = "HEARTBEAT_ACK"
        const val REMOTE_COMMAND = "REMOTE_COMMAND"
        const val COMMAND_ACK = "COMMAND_ACK"
        const val SYSTEM_ALERT = "SYSTEM_ALERT"
        const val OPERATOR_DECISION = "OPERATOR_DECISION"
    }

    object DeviceRoles {
        const val CAPTURE = "capture"
        const val REMOTE_CONTROL = "remote_control"
    }

    object Commands {
        const val CALIBRATE = "CALIBRATE"
        const val START = "START"
        const val PAUSE = "PAUSE"
        const val STOP = "STOP"
        const val STATUS = "STATUS"
        const val SET_AI_PROVIDER = "SET_AI_PROVIDER"
    }

    object OperatorDecisions {
        const val REQUERY_AI = "REQUERY_AI"
        const val SKIP_QUESTION = "SKIP_QUESTION"
        const val USE_DATABASE_ANSWER = "USE_DATABASE_ANSWER"
        const val USE_AI_ANSWER = "USE_AI_ANSWER"
    }
}
