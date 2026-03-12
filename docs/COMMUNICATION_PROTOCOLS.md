
# SIMULATO COMMUNICATION PROTOCOL SPECIFICATION
## Project: Simulato

Version: 1.1
Status: Authoritative Communication Protocol Document

> **Revision 1.1 (2026-03-05):** Updated WebSocket endpoint to include device_id path parameter, moved CALIBRATE command to Capture Mode, added CALIBRATION_RESULT message type, clarified single-role enforcement.

---

# 1. PURPOSE

This document defines the **communication protocols used between all devices** in the Simulato system.

The system is a **distributed architecture** composed of the following nodes:

1. Main Control PC (Controller)
2. Raspberry Pi (HID Injector)
3. Mobile Device running Simulato App
   - Capture Mode
   - Remote Control Mode

Communication protocols must ensure:

- deterministic system behavior
- reliable command delivery
- acknowledgement of critical actions
- failure detection
- device synchronization

All messages must follow the schemas defined in this document.

---

# 2. NETWORK TOPOLOGY

All Simulato devices connect to the **same WiFi network** (any shared network — home router, mobile hotspot, etc.). No special network configuration, DHCP setup, or static IP assignments are required.

All devices communicate through the **Main Control PC**.

Topology:

Mobile App (Capture Mode) → Controller (by IP entered in app)  
Mobile App (Remote Mode) → Controller (by IP entered in app)  
Controller → Raspberry Pi (by IP set in config)

The Raspberry Pi **does not communicate directly with the mobile devices**.

---

# 3. TRANSPORT LAYER

Transport protocols:

Mobile App ↔ Controller: HTTP + WebSocket
Controller ↔ Raspberry Pi: TCP Socket

WebSocket URL format:

    ws://<CONTROLLER_IP>:<CONTROLLER_PORT>/ws/<DEVICE_ID>

The `device_id` is embedded in the WebSocket URL path so the controller can associate the persistent connection with a registered device without a secondary handshake.

---

# 4. MESSAGE FORMAT

All communication messages must use **JSON format**.

General message structure:

{
  "type": "MESSAGE_TYPE",
  "device_id": "DEVICE_IDENTIFIER",
  "timestamp": "ISO8601_TIMESTAMP",
  "payload": { }
}

Fields:

type → message type identifier  
device_id → unique device identifier  
timestamp → event time  
payload → message data

---

# 5. DEVICE REGISTRATION

When a device connects to the controller, it must register.

**Constraint:** Each device_id may hold only one role at a time. If the same device_id re-registers with a different role, the old registration is overwritten. Only one device per role is allowed at any given time (e.g. only one capture device, only one remote control device).

Message:

    POST /api/register

    {
     "type": "DEVICE_REGISTER",
     "device_id": "phone_capture_01",
     "timestamp": "ISO8601_TIMESTAMP",
     "payload": {
       "device_role": "capture | remote_control | pi"
     }
    }

Controller response:

    {
     "type": "REGISTER_ACK",
     "payload": {
       "status": "accepted"
     }
    }

---

# 6. HEARTBEAT PROTOCOL

All devices must send periodic heartbeats.

Purpose:

- detect device failure
- maintain connection health

Interval:

Every 5 seconds.

Message:

    POST /api/heartbeat

    {
     "type": "HEARTBEAT",
     "device_id": "phone_capture_01",
     "timestamp": "ISO8601_TIMESTAMP"
    }

Controller response:

    {
     "type": "HEARTBEAT_ACK"
    }

If heartbeat fails for **15 seconds**, device is considered disconnected.

---

# 7. IMAGE CAPTURE PROTOCOL

Used by Capture Mode.

Endpoint:

    POST /api/upload_image

Payload (JSON, base64-encoded image):

    {
     "device_id": "phone_capture_01",
     "timestamp": "ISO8601",
     "image": "BASE64_ENCODED_JPEG"
    }

Controller response:

    {
     "status": "received"
    }

The controller decodes the base64 image and processes it through the capture pipeline.
During **CALIBRATION** state, the image is routed to the calibration workflow instead of the question processing pipeline.

---

# 8. REMOTE CONTROL COMMAND PROTOCOL

Used by Remote Control Mode.

Commands:

    START
    PAUSE
    STOP
    STATUS

Example message:

    POST /api/command

    {
     "type": "REMOTE_COMMAND",
     "device_id": "phone_remote_01",
     "timestamp": "ISO8601_TIMESTAMP",
     "payload": {
       "command": "START"
     }
    }

Controller response:

    {
     "type": "COMMAND_ACK",
     "payload": {
       "status": "accepted"
     }
    }

---

# 8A. CALIBRATE COMMAND PROTOCOL

The **CALIBRATE** command is primarily sent by the **Capture Mode phone**,
but the **Remote Control phone** may also request recalibration mid-exam.

When received, the controller:
1. Transitions to `CALIBRATION` state
2. Sends a `CAPTURE_IMAGE` command back to the capture phone via WebSocket
3. Awaits the uploaded image
4. Runs OpenCV-based screen element detection
5. Saves `config/grid_map.json`
6. Sends `CALIBRATION_RESULT` back to both phones
7. Transitions to `IDLE` state (or back to `PAUSED`/`RUNNING` depending on context)

Calibrate request from Capture Mode:

    POST /api/command

    {
     "type": "REMOTE_COMMAND",
     "device_id": "phone_capture_01",
     "timestamp": "ISO8601_TIMESTAMP",
     "payload": {
       "command": "CALIBRATE"
     }
    }

Recalibrate request from Remote Control Mode:

    POST /api/command

    {
     "type": "REMOTE_COMMAND",
     "device_id": "phone_remote_01",
     "timestamp": "ISO8601_TIMESTAMP",
     "payload": {
       "command": "CALIBRATE"
     }
    }

Calibration result (controller → phones, via WebSocket):

    {
     "type": "CALIBRATION_RESULT",
     "payload": {
       "success": true,
       "positions": { "A": [15, 8], "B": [15, 10], ... },
       "error": ""
     }
    }

---

# 9. ALERT PROTOCOL

When the controller detects an anomaly, it sends an alert to the remote control device.

Alert message:

{
 "type": "SYSTEM_ALERT",
 "payload": {
   "alert_type": "AI_CONFLICT",
   "message": "AI answer conflicts with database answer"
 }
}

Remote device must display the alert and request operator decision.

---

# 10. OPERATOR DECISION PROTOCOL

Operator sends decision back to controller.

Possible decisions:

REQUERY_AI  
SKIP_QUESTION  
USE_DATABASE_ANSWER  
USE_AI_ANSWER

Example:

{
 "type": "OPERATOR_DECISION",
 "payload": {
   "decision": "REQUERY_AI"
 }
}

Controller must acknowledge.

---

# 11. PI COMMAND PROTOCOL

Controller sends commands to Raspberry Pi.

Commands:

CLICK_A  
CLICK_B  
CLICK_C  
CLICK_D  
CLICK_NEXT  
SCROLL_LEFT  
SCROLL_RIGHT

Example:

{
 "type": "PI_COMMAND",
 "payload": {
   "command": "CLICK_A"
 }
}

---

# 12. PI EXECUTION RESPONSE

The Raspberry Pi must respond after executing a command.

Response:

{
 "type": "PI_RESPONSE",
 "payload": {
   "command": "CLICK_A",
   "status": "executed"
 }
}

Controller then verifies the result visually.

---

# 13. COMMAND ACKNOWLEDGEMENT RULE

All commands must be acknowledged.

Flow:

Controller → Command → Device  
Device → ACK

If no ACK received within **3 seconds**, controller retries command.

Maximum retries:

3

After failure:

System enters ERROR state.

---

# 14. TIMEOUT RULES

Timeout definitions:

Heartbeat timeout: 15 seconds  
Command ACK timeout: 3 seconds  
Image upload timeout: 10 seconds

Timeout events must trigger logging and alert handling.

---

# 15. SECURITY MODEL

Since the system operates within a trusted local network, security mechanisms are minimal.

Basic protections:

- device ID verification
- role-based single-device enforcement (one device per role)
- connection origin validation

Future enhancements may include authentication tokens.

---

# 16. ERROR HANDLING

Errors include:

- device disconnection
- command timeout
- invalid message format

Controller response:

1. log error
2. trigger alert
3. pause execution

Operator intervention required.

---

# 17. FINAL DECLARATION

This protocol defines the **official communication standard for Simulato devices**.

All implementations must follow this specification to ensure:

- reliable distributed communication
- deterministic system execution
- stable automation behavior
