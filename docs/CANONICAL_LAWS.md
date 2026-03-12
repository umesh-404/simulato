# CANONICAL SYSTEM LAWS

## Project: Simulato

Version: 1.0\
Status: Authoritative System Law Document

------------------------------------------------------------------------

# 1. PURPOSE

This document defines the **immutable system laws** that govern the
architecture, execution behavior, and data integrity of the Simulato
platform.

Simulato is a **distributed automation and research simulation system**
designed to evaluate AI-assisted exam solving workflows.

These laws exist to ensure:

-   deterministic system behavior
-   reproducibility of experiments
-   reliable distributed execution
-   dataset integrity
-   predictable automation control

These laws are **above**:

-   implementation decisions
-   performance optimizations
-   convenience features
-   development shortcuts

If any component violates a law defined in this document, that component
is **invalid by definition**.

------------------------------------------------------------------------

# 2. LAW HIERARCHY

Laws are ordered by precedence.

Lower-numbered laws override higher-numbered laws.

------------------------------------------------------------------------

# 3. CORE SYSTEM PRINCIPLES

------------------------------------------------------------------------

## LAW 1 --- DETERMINISTIC EXECUTION

Simulato must behave deterministically.

Given identical inputs, the system must produce identical outputs.

Inputs include:

-   captured screenshots
-   database state
-   AI model responses

If these inputs remain unchanged, Simulato must:

-   select the same answer
-   execute the same input commands
-   produce identical logs and results

Deterministic AI output is enforced via **Structured Output (JSON Schema)** protocols. Randomness in system logic is forbidden.

------------------------------------------------------------------------

## LAW 2 --- REPLAYABILITY

Every test run must be reproducible.

Simulato must store sufficient data to replay any test run.

A replay must produce the exact same decisions and actions.

Required stored artifacts:

-   screenshots
-   AI responses
-   decision logs
-   executed input commands

Replay capability exists to support:

-   debugging
-   experiment verification
-   dataset validation

------------------------------------------------------------------------

## LAW 3 --- EXTERNAL INTERACTION ONLY

Simulato must interact with exam systems **externally**.

All system actions must occur through:

-   camera capture
-   external hardware input devices

The system must never modify, intercept, or inject logic into exam
software internally.

------------------------------------------------------------------------

## LAW 4 --- DISTRIBUTED SYSTEM MODEL

Simulato is a distributed system composed of multiple nodes:

-   Exam Laptop
-   Raspberry Pi (HID injector)
-   Main Control PC
-   Capture Phone
-   Remote Control Phone

Each node has a clearly defined role.

No node may assume responsibilities belonging to another node.

System coordination must occur through the **Main Control PC**.

------------------------------------------------------------------------

## LAW 5 --- HARDWARE INPUT TRANSACTION SAFETY

All hardware input actions must be treated as transactions.

Execution sequence:

1.  send input command
2.  verify visual confirmation
3.  if verification fails → retry
4.  if retry fails → halt execution

Silent failures are forbidden.

When repeated failure occurs:

-   system must trigger alert sound
-   system must pause execution
-   system must await manual operator decision

------------------------------------------------------------------------

## LAW 6 --- HUMAN INTERVENTION AUTHORITY

When the system encounters an inconsistency or failure, execution must
pause and await operator input.

Examples include:

-   conflicting AI and database answers
-   hardware input failure
-   unexpected screen state

The system must:

1.  trigger audible alert
2.  display alert on remote control mobile app
3.  present operator options

Operator decision options:

-   re-query AI
-   skip question
-   continue with database answer
-   continue with AI answer

No automatic override is permitted.

------------------------------------------------------------------------

## LAW 7 --- QUESTION DATASET INTEGRITY

Once a question is recorded in the database, its stored representation
must remain immutable.

Stored components include:

-   canonical question text
-   option texts
-   correct answer text
-   question hash

If any of these components change, the system must:

-   create a new version record
-   preserve the previous version

Silent modification of stored questions is forbidden.

------------------------------------------------------------------------

## LAW 8 --- ANSWER MATCHING BY CONTENT

Answer selection must be determined using **option content**, not option
position.

This ensures correct behavior when exam systems shuffle option order.

The system must:

1.  identify the stored correct answer text
2.  match it against current option texts
3.  determine the correct option position dynamically

Reliance on stored option letters (A/B/C/D) is forbidden.

------------------------------------------------------------------------

## LAW 9 --- AI RESPONSE VALIDATION

AI responses must never automatically override stored database answers.

When AI response conflicts with stored answer:

system must pause and notify the operator.

Execution must not continue until the operator provides instruction.

------------------------------------------------------------------------

## LAW 10 --- FULL QUESTION SNAPSHOT STORAGE

Simulato must store a full snapshot for every captured question.

Required stored elements:

-   original screenshot
-   extracted question text
-   extracted options
-   AI response
-   selected answer
-   decision metadata

This ensures:

-   experiment reproducibility
-   dataset transparency
-   debugging capability

------------------------------------------------------------------------

## LAW 11 --- COMPLETE EXECUTION LOGGING

Every system action must be logged.

Logs must include:

-   timestamps
-   question identifiers
-   AI calls
-   decision outcomes
-   input commands sent to hardware
-   error conditions
-   operator interventions

Silent execution paths are forbidden.

------------------------------------------------------------------------

## LAW 12 --- FAILURE VISIBILITY

Failures must never be silent.

When a failure occurs:

1.  execution halts
2.  alert sound is triggered
3.  operator interface displays the issue
4.  operator decision is required

The system must not guess recovery behavior.

------------------------------------------------------------------------

## LAW 13 --- CONTROLLER AUTHORITY

The Main Control PC is the authoritative orchestrator of the system.

Responsibilities include:

-   coordinating all nodes
-   processing captured images
-   performing AI calls
-   managing the database
-   dispatching hardware commands
-   managing system state

No other node may make orchestration decisions.

------------------------------------------------------------------------

## LAW 14 --- SYSTEM STATE EXPLICITNESS

The system must always operate within a defined state.

Valid states:

-   IDLE
-   CALIBRATION
-   RUNNING
-   PAUSED
-   ERROR
-   STOPPED

All transitions between states must be logged.

Implicit state changes are forbidden.

------------------------------------------------------------------------

## LAW 15 --- NETWORK USAGE DECLARATION

Network usage within Simulato must be explicit.

The system is designed to operate within a local network environment.

Internet access is required only for:

-   AI API calls (e.g., Grok Cloud or Ollama Local)

All other components must function locally.

------------------------------------------------------------------------

# 4. AI BEHAVIOR GUIDELINES

AI models in Simulato are used strictly for:

-   interpreting question images
-   extracting structured question data
-   proposing candidate answers

AI does not control system execution.

AI output must always be validated before action.

------------------------------------------------------------------------

# 5. FINAL DECLARATION

These laws define the identity and operational constraints of Simulato.

They ensure that the system remains:

-   deterministic
-   reproducible
-   transparent
-   controllable

Any system component that violates these laws is **not compliant with
Simulato**.
