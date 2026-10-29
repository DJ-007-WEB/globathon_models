# Backend — Solar Recovery Intelligence

## Purpose

This branch is responsible for the application API and orchestration layer. It connects the frontend to the available analysis components and returns structured, traceable results.

## Intended responsibilities

1. Define and validate the API requests received from the frontend.
2. Validate and normalize incoming data only as required by the agreed application contract.
3. Coordinate calls to the separate ML component and local LLM component when they are available.
4. Keep deterministic calculations and numeric business logic in tested code or the appropriate ML/calculation layer.
5. Pass structured evidence and results to the LLM for explanation rather than asking the LLM to invent measurements or perform authoritative calculations.
6. Return predictable JSON responses, including missing-data notes, errors, and uncertainty where available.
7. Apply timeouts and useful error handling when a component is unavailable.
8. Provide the frontend with a stable, documented integration contract.

The exact endpoints, schema, and which layer owns each calculation must be agreed with the team before implementation. This README describes intended responsibilities, not completed functionality.

## LLM integration

The local model is intended to run through Ollama, currently installed on the developer's Windows laptop. A request to `http://localhost:11434` reaches the machine making that request: if the backend is deployed on a different server, its `localhost` will not reach the developer's laptop. The team must choose and test an architecture that preserves the hackathon's local-inference requirement.

The backend should send the LLM only the structured facts, calculations, and hypotheses it is allowed to explain. It should validate or constrain the response format and handle model timeouts or malformed output.

## Integration contract

Before implementation, document:
- Request fields, units, timestamps, and required/optional inputs.
- Structured ML result fields and their provenance.
- LLM input context and expected response format.
- Error responses and insufficient-evidence behaviour.
- Model availability, timeouts, and local/deployed network assumptions.

## Out of scope

This branch does not own the frontend UI, the teammate's ML-model training/implementation, or the LLM fine-tuning pipeline itself.

## Current status

This branch is being reset for a fresh implementation. No backend endpoints or integration code are claimed as complete yet.
