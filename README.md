# Frontend — Solar Recovery Intelligence

## Purpose

This branch is responsible for the operator-facing user interface for the Globathon 2026 Solar Recovery Intelligence project. It should make solar-plant analysis understandable and actionable without making unsupported technical claims.

## Intended user flow

The interface is expected to support a workflow such as:

1. Let the user provide or select the plant data and analysis context supported by the backend.
2. Show the analysis status and handle missing, invalid, or incomplete input clearly.
3. Present returned performance findings and relevant evidence in a readable form.
4. Display possible explanations as hypotheses when they are not confirmed facts.
5. Present recovery-oriented suggestions and their assumptions when the backend supplies them.
6. Make errors and insufficient-evidence outcomes clear to the user.

The exact screens, upload format, visualizations, and final workflow should be agreed with the team before implementation; this README does not assert that these features are already built.

## Integration boundary

- The frontend calls the backend API; it should not call Ollama directly or implement ML calculations itself.
- It renders structured backend results and should preserve labels for observations, estimates, hypotheses, and uncertainty.
- It should not fabricate generation figures, diagnoses, savings, or confidence values.
- API routes and request/response schemas must be agreed with the backend branch before wiring the interface.
- Loading, validation, empty, success, and error states should be considered.

## Responsibilities

- Build a clear, responsive, accessible interface for plant analysis.
- Present evidence and recommendations in a way that is easy to understand.
- Validate user input at the interface level while relying on the backend for authoritative validation.
- Keep API configuration separate from UI components and avoid committing secrets.
- Test the interface with both valid responses and insufficient-data/error responses.

## Out of scope

This branch does not own model training, local LLM inference, backend orchestration, or the teammate's ML-model implementation.

## Current status

This branch is being reset for a fresh implementation. No frontend implementation is claimed as complete yet.
