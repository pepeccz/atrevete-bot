# Spec: Escalation mode — structured intake

## Purpose
This specification defines the changes needed to fix the escalation mode to implement structured intake before handing off to a human agent. Currently, the escalation mode immediately calls the escalate_to_human tool without capturing issue details or contact preferences.

## Affected Domains
- agent/modes/escalation_mode.py
- agent/state/schemas.py
- agent/tools/escalation_tools.py

## ADDED Requirements

### Requirement: Structured Escalation Intake Flow
The system SHALL implement a multi-step escalation flow that captures issue description and contact preference before handing off to a human agent.

#### Scenario: Happy path escalation
- GIVEN user expresses intent to escalate (e.g., "Me cobraron mal")
- WHEN user is in any mode and triggers escalation
- THEN system enters ESCALATION mode and asks for issue description
- WHEN user provides issue description
- THEN system stores issue description and asks for preferred contact method
- WHEN user selects contact method (phone/WhatsApp/email)
- THEN system stores contact preference and calls escalate_to_human with full context
- WHEN tool call succeeds
- THEN system shows empathy message and handoff confirmation

#### Scenario: Urgent escalation path
- GIVEN user expresses urgent need for human agent (e.g., "QUIERO HABLAR CON UNA PERSONA YA")
- WHEN user triggers escalation with urgent language
- THEN system skips intake questions and immediately escalates with context "urgent_request"
- WHEN tool is called
- THEN system shows immediate handoff confirmation

#### Scenario: Context-rich escalation
- GIVEN user has already provided issue details and contact preference in conversation
- WHEN user triggers escalation
- THEN system extracts existing context and proceeds directly to tool call
- WHEN tool is called with pre-existing context
- THEN system confirms handoff without repeating questions

#### Scenario: Already escalated protection
- GIVEN conversation has already been escalated (escalation_triggered=True)
- WHEN user sends additional messages
- THEN system shows "Ya estamos en contacto con el equipo..." message instead of repeating intake

### Requirement: Enhanced Escalation Tool Parameters
The system SHALL modify the escalate_to_human tool to accept issue summary and contact preference parameters.

#### Scenario: Tool receives correct parameters
- GIVEN escalation has collected issue summary and contact preference
- WHEN escalate_to_human tool is invoked
- THEN tool receives _conversation_id, _customer_phone, issue_summary, contact_preference, and reason parameters
- WHEN tool processes the request
- THEN escalation service receives full context for proper handling

## MODIFIED Requirements

### Requirement: Escalation Mode State Management
The system SHALL modify ConversationState to track escalation intake progress.

#### Scenario: State tracks escalation steps
- GIVEN conversation enters ESCALATION mode
- WHEN system initializes escalation handling
- THEN mode_context includes escalation_step set to "issue_intake"
- WHEN issue description is captured
- THEN mode_context updates escalation_step to "contact_preference" and stores issue_summary
- WHEN contact preference is captured
- THEN mode_context updates escalation_step to "ready_to_handoff" and stores contact_preference

### Requirement: Router Transition After Escalation
The system SHALL modify escalation mode to allow transition out of ESCALATION after handoff.

#### Scenario: Router allows transition after handoff
- GIVEN escalation has been completed (tool called successfully)
- WHEN user sends subsequent message
- THEN system does NOT remain locked in ESCALATION mode
- WHEN router processes next intent
- THEN system can transition to appropriate mode based on new intent

## REMOVED Requirements

### Requirement: Immediate Escalation Without Intake
The system SHALL NOT immediately call escalate_to_human tool upon escalation trigger without capturing context.

(Previously: Escalation mode called tool immediately with only conversation_id and customer_phone)

### Requirement: Perpetual Escalation Loop
The system SHALL NOT keep conversation locked in ESCALATION mode after handoff.

(Previously: Once escalation_triggered=True, all subsequent messages stayed in ESCALATION mode returning same response)

## Acceptance Criteria

### Criteria 1: Structured Intake Flow
- Elena says "Me cobraron mal" → bot captures issue → asks contact method → calls tool → confirms handoff
- System must store issue_summary and contact_preference in state before tool invocation
- Tool must receive all four parameters: _conversation_id, _customer_phone, issue_summary, contact_preference

### Criteria 2: No Canned Response Loop
- Turns 2+ in escalation should NOT be identical responses
- System must progress through intake steps based on what information has been collected
- After handoff, system should allow mode transitions based on new user intents

### Criteria 3: Proper Tool Integration
- escalate_to_human.ainvoke must be called with correct parameter names
- Reason parameter should be "manual_request" for standard escalations
- System must handle tool success/failure appropriately

### Criteria 4: Context Preservation
- If user provides issue + contact in first message, system parses and uses that context
- System must not ask for information already provided
- Escalation timestamp should be recorded for audit trail

## Risks
- Tool parameter mismatch: If tool signature doesn't match expected parameters, calls will fail
- State corruption: Incorrect mode_context updates could break escalation flow
- Router confusion: Improper handling of escalation_triggered flag could cause looping
- UX regression: Overly complex intake could frustrate users seeking immediate help