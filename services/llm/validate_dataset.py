
import json
from pathlib import Path

ROOT = Path("data/synthetic")
EXPECTED = {
    "train.jsonl": 1200,
    "validation.jsonl": 150,
    "test.jsonl": 150,
}

required_fields = {
    "id", "source_type", "scenario_category", "prompt", "response"
}

required_response_fields = {
    "summary", "observations", "possible_causes",
    "supporting_evidence", "recommended_checks",
    "limitations", "confidence"
}

total = 0
all_ids = set()
errors = []

for filename, expected_count in EXPECTED.items():
    path = ROOT / filename

    if not path.exists():
        errors.append(f"Missing file: {path}")
        continue

    count = 0

    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                errors.append(
                    f"{filename}:{line_number}: Invalid JSON: {error}"
                )
                continue

            count += 1
            missing = required_fields - record.keys()

            if missing:
                errors.append(
                    f"{filename}:{line_number}: Missing {missing}"
                )
                continue

            if record["id"] in all_ids:
                errors.append(f"Duplicate ID: {record['id']}")
            all_ids.add(record["id"])

            response = record["response"]

            if not isinstance(response, dict):
                errors.append(f"{record['id']}: response must be an object")
                continue

            missing_response = required_response_fields - response.keys()

            if missing_response:
                errors.append(
                    f"{record['id']}: Missing response fields "
                    f"{missing_response}"
                )

            if record["source_type"] != "synthetic":
                errors.append(f"{record['id']}: Unexpected source type")

            if not isinstance(record["prompt"], str) or not record["prompt"].strip():
                errors.append(f"{record['id']}: Empty prompt")

            if response.get("confidence") not in {"low", "moderate", "high"}:
                errors.append(f"{record['id']}: Invalid confidence label")

    print(f"{filename}: {count}/{expected_count} records")
    if count != expected_count:
        errors.append(
            f"{filename}: expected {expected_count}, found {count}"
        )

    total += count

if errors:
    print(f"\nFAILED: {len(errors)} validation errors")
    for error in errors[:30]:
        print("-", error)
    raise SystemExit(1)

print(f"\nPASSED: {total} records passed structural validation.")
print("This does not establish factual accuracy or training quality.")
