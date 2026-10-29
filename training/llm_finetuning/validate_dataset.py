#!/usr/bin/env python3
"""Validate supervised fine-tuning JSONL files for Solar Recovery Intelligence."""

import argparse
import json
from pathlib import Path

REQUIRED_KEYS = {
    "confirmed_findings",
    "possible_explanations",
    "recommended_next_checks",
    "limitations",
}
ALLOWED_ROLES = {"system", "user", "assistant"}


def load_jsonl(path: Path):
    rows = []
    errors = []

    if not path.exists():
        return rows, [f"File does not exist: {path}"]

    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{path}:{line_number}: invalid JSON: {exc}")
                continue

            if not isinstance(row, dict):
                errors.append(f"{path}:{line_number}: each row must be an object")
                continue

            messages = row.get("messages")
            if not isinstance(messages, list) or len(messages) < 3:
                errors.append(
                    f"{path}:{line_number}: messages must be a list with "
                    "at least system, user, and assistant messages"
                )
                continue

            roles = [message.get("role") for message in messages
                     if isinstance(message, dict)]
            if len(roles) != len(messages):
                errors.append(f"{path}:{line_number}: every message must be an object")
                continue

            if any(role not in ALLOWED_ROLES for role in roles):
                errors.append(
                    f"{path}:{line_number}: roles must be system, user, or assistant"
                )
                continue

            if roles[0] != "system" or roles[-1] != "assistant":
                errors.append(
                    f"{path}:{line_number}: first role must be system and "
                    "last role must be assistant"
                )
                continue

            if "user" not in roles:
                errors.append(f"{path}:{line_number}: at least one user message is required")
                continue

            if any(
                not isinstance(message.get("content"), str)
                or not message["content"].strip()
                for message in messages
            ):
                errors.append(
                    f"{path}:{line_number}: every message needs non-empty string content"
                )
                continue

            try:
                target = json.loads(messages[-1]["content"])
            except json.JSONDecodeError:
                errors.append(
                    f"{path}:{line_number}: assistant target must be a JSON object"
                )
                continue

            if not isinstance(target, dict):
                errors.append(
                    f"{path}:{line_number}: assistant target must be a JSON object"
                )
                continue

            missing = REQUIRED_KEYS - set(target)
            if missing:
                errors.append(
                    f"{path}:{line_number}: assistant target missing keys: "
                    + ", ".join(sorted(missing))
                )
                continue

            for key in REQUIRED_KEYS:
                value = target[key]
                if not isinstance(value, list) or any(
                    not isinstance(item, str) for item in value
                ):
                    errors.append(
                        f"{path}:{line_number}: target key {key!r} "
                        "must be an array of strings"
                    )
                    break
            else:
                rows.append(row)

    return rows, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    args = parser.parse_args()

    train_rows, train_errors = load_jsonl(args.train)
    validation_rows, validation_errors = load_jsonl(args.validation)
    errors = train_errors + validation_errors

    print(f"Training examples valid: {len(train_rows)}")
    print(f"Validation examples valid: {len(validation_rows)}")

    if not train_rows:
        errors.append("Training set is empty.")
    if not validation_rows:
        errors.append("Validation set is empty.")

    if errors:
        print("\nDataset validation FAILED:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    print("Dataset validation PASSED. Human review of factual correctness is still required.")


if __name__ == "__main__":
    main()
