# Business Requirements Document (BRD)

## AI-Assisted Exam Simulation System

Version: 1.0\
Document Status: Final\
Prepared For: Technical Evaluation Department

------------------------------------------------------------------------

# 1. Executive Summary

The AI-Assisted Exam Simulation System is designed to simulate realistic
scenarios where students may use artificial intelligence tools to assist
in answering exam questions.

The system will enable the technical department to:

-   Evaluate how AI could influence exam outcomes.
-   Measure AI accuracy in answering test questions.
-   Analyze the feasibility of AI-assisted cheating scenarios.
-   Understand the vulnerabilities of existing examination systems.

The platform will automate question capture, AI processing, and answer
selection while logging detailed analytical data.

------------------------------------------------------------------------

# 2. Business Objectives

The primary objectives of this system are:

1.  **Simulation of AI-assisted exam completion**
2.  **Identification of exam security weaknesses**
3.  **Evaluation of AI accuracy on exam questions**
4.  **Creation of datasets for exam analysis**
5.  **Assessment of response time and automation feasibility**
6.  **Development of insights for improving exam security systems**

------------------------------------------------------------------------

# 3. Business Problem Statement

Educational institutions are increasingly concerned about the potential
misuse of AI tools during examinations.

Current exam security systems focus primarily on:

-   browser restrictions
-   device monitoring
-   network monitoring

However, these systems may not account for **external device-based AI
assistance**.

The institution requires a controlled simulation platform to:

-   evaluate this risk
-   understand how AI may interact with exam questions
-   develop mitigation strategies.

------------------------------------------------------------------------

# 4. Stakeholders

  Stakeholder                 Role
  --------------------------- ---------------------------
  Examination Department      Project sponsor
  Technical Department        System operators
  Academic Review Committee   Evaluation of results
  Institution Management      Strategic decision makers
  Security Research Team      Vulnerability analysis

------------------------------------------------------------------------

# 5. Business Scope

## In Scope

The system will:

-   simulate AI-assisted answering of MCQ tests
-   capture exam questions using an external camera
-   analyze questions using an AI model
-   automatically select answers
-   store questions and answers for analysis
-   provide remote system control
-   generate structured logs and datasets

## Out of Scope

The system will not:

-   modify exam content
-   interact with exam servers directly
-   bypass exam browser protections internally
-   alter exam software

------------------------------------------------------------------------

# 6. Key Business Requirements

## 6.1 AI Simulation Capability

The system must simulate how a student could use AI assistance during an
exam using external hardware.

Capabilities include:

-   capturing questions
-   sending them to an AI model
-   selecting answers automatically

------------------------------------------------------------------------

## 6.2 Automated Question Processing

The system must automatically:

-   detect questions
-   extract options
-   determine answers using AI

------------------------------------------------------------------------

## 6.3 Local Question Database

The system must maintain a local repository of questions to:

-   reduce repeated AI calls
-   allow faster responses
-   build a dataset for analysis

------------------------------------------------------------------------

## 6.4 Test Context Management

Each test must be registered by name before execution.

All captured questions must be linked to the test context to:

-   restrict search space
-   improve matching speed
-   organize datasets.

------------------------------------------------------------------------

## 6.5 Remote Control Capability

Operators must be able to control the system remotely using a mobile
device.

Available commands:

-   calibrate system
-   start test
-   pause test
-   stop test
-   monitor system status

------------------------------------------------------------------------

## 6.6 Fail-Safe Detection

The system must detect unexpected conditions such as:

-   exam login screens
-   error pages
-   unexpected layouts

When detected:

-   automation must stop
-   an alarm must be triggered
-   operator must be notified

------------------------------------------------------------------------

# 7. Business Benefits

Implementation of this system provides:

### 7.1 Exam Security Insights

Institutions gain understanding of potential vulnerabilities in exam
systems.

### 7.2 AI Capability Assessment

Institutions can evaluate:

-   how well AI answers exam questions
-   which subjects are most vulnerable

### 7.3 Policy Development

Results can help shape policies regarding:

-   AI usage
-   exam monitoring
-   device restrictions

### 7.4 Dataset Generation

The system automatically generates a dataset of:

-   questions
-   options
-   answers
-   AI accuracy metrics

------------------------------------------------------------------------

# 8. Success Criteria

The project will be considered successful when:

-   the system captures exam questions reliably
-   AI responses are generated accurately
-   answers are automatically selected
-   questions are stored in the database
-   repeated questions are answered locally
-   operators can control the system remotely
-   logs provide meaningful analytical data

------------------------------------------------------------------------

# 9. Risks and Considerations

  Risk                      Description
  ------------------------- ---------------------------------------
  AI accuracy limitations   AI may provide incorrect answers
  Camera quality            Poor capture may reduce OCR accuracy
  Network dependency        Cloud AI API requires internet (Local Ollama does not)
  Hardware alignment        Camera positioning must be precise

------------------------------------------------------------------------

# 10. Assumptions

The system assumes:

-   the exam laptop allows USB input devices
-   camera capture provides readable images
-   AI API services remain available
-   tests consist of multiple-choice questions

------------------------------------------------------------------------

# 11. Constraints

The project must operate within the following constraints:

-   limited number of tests
-   secure browser restrictions
-   fixed exam interface layout
-   time constraints for test execution

------------------------------------------------------------------------

# 12. Deliverables

The project must deliver:

1.  Working automation system
2.  AI-assisted simulation results
3.  Question dataset
4.  System logs
5.  performance metrics

------------------------------------------------------------------------

# 13. Timeline Expectations

Estimated phases:

  Phase         Description
  ------------- ---------------------------------
  Planning      Requirements and architecture
  Development   Software and system integration
  Testing       Simulation runs
  Analysis      Data review and reporting

------------------------------------------------------------------------

# 14. Key Performance Indicators (KPIs)

The system must measure:

-   AI answer accuracy
-   average response time
-   number of API calls
-   number of cached question hits
-   system reliability during test runs

------------------------------------------------------------------------

# 15. Future Enhancements

Potential future improvements include:

-   automated vulnerability reports
-   AI accuracy dashboards
-   additional exam formats
-   improved question matching algorithms

------------------------------------------------------------------------

# 16. Approval

This document defines the business requirements for the AI-Assisted Exam
Simulation System and serves as the baseline for system development and
evaluation.

------------------------------------------------------------------------

# End of Business Requirements Document
