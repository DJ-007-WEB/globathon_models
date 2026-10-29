
import json
import random
from pathlib import Path

random.seed(42)

ROOT = Path("data/synthetic")
ROOT.mkdir(parents=True, exist_ok=True)

SCENARIOS = [
    {
        "category": "low_irradiance",
        "observation": "Irradiance is 320 W/m², below the expected 650 W/m². Plant output is low, and no inverter alarms are reported.",
        "summary": "Low irradiance may explain part of the reduced output. Compare generation with an irradiance-adjusted baseline before concluding that a fault exists."
    },
    {
        "category": "inverter_fault",
        "observation": "Inverter INV-03 reports a fault and has zero output while other inverters are producing power. The fault-code meaning is unavailable.",
        "summary": "INV-03 requires investigation. The exact failure mode is unknown; check the inverter model manual, fault code and event logs before recommending a repair."
    },
    {
        "category": "high_temperature",
        "observation": "Module temperature is 68°C and irradiance is 900 W/m². Output is below the temperature-adjusted expectation.",
        "summary": "Elevated module temperature may reduce efficiency, but it does not prove the sole cause. Check the module temperature coefficient and investigate other possible losses."
    },
    {
        "category": "grid_curtailment",
        "observation": "Plant available power is estimated at 900 kW, export is capped at 500 kW, and a matching grid curtailment event is logged.",
        "summary": "The curtailment record supports grid restrictions as a likely explanation. Verify event timing, export limits and meter readings."
    },
    {
        "category": "sensor_quality",
        "observation": "Irradiance is reported as -45 W/m² at noon, while nearby readings are 700–850 W/m². Sensor quality is unknown.",
        "summary": "The reading is suspicious and may reflect sensor or data-processing problems. Check calibration, timestamps, units and adjacent readings."
    },
    {
        "category": "soiling",
        "observation": "Output is 12% below a validated irradiance-adjusted baseline. An inspection reports visible dust on several modules.",
        "summary": "Soiling is a plausible contributor. Quantify its impact and check whether the inspected modules represent the affected plant area."
    },
    {
        "category": "normal_operation",
        "observation": "Output is 96% of validated expected power for current irradiance and temperature. No active alarms are reported.",
        "summary": "The readings are broadly consistent with expected operation. Continue routine monitoring and examine longer-term trends."
    },
    {
        "category": "conflicting_data",
        "observation": "The dashboard reports an inverter online, but detailed telemetry says offline at the same timestamp. Two meters disagree.",
        "summary": "The evidence conflicts, so a reliable diagnosis should be deferred until timestamps, meter sources and status definitions are reconciled."
    },
    {
        "category": "insufficient_data",
        "observation": "Plant output is low, but irradiance, inverter status, grid status and sensor-quality information are unavailable.",
        "summary": "There is insufficient evidence to determine the cause. Obtain time-aligned irradiance, inverter, grid and sensor-quality data."
    },
]

def make_record(number, split):
    case = random.choice(SCENARIOS)

    prompt = (
        "Analyse this solar plant performance case. Separate observations "
        "from possible explanations, avoid unsupported conclusions, and "
        "recommend relevant next checks.\n\n"
        f"Plant observations: {case['observation']}"
    )

    response = {
        "summary": case["summary"],
        "observations": [case["observation"]],
        "possible_causes": [case["category"]],
        "supporting_evidence": [
            "Use only the observations supplied in this synthetic case."
        ],
        "recommended_checks": [
            "Verify timestamps, units and sensor-quality flags.",
            "Compare output with an irradiance- and temperature-adjusted expectation.",
            "Review relevant inverter and grid event logs."
        ],
        "limitations": [
            "Synthetic example, not a real plant record.",
            "A definitive diagnosis requires site-specific evidence."
        ],
        "confidence": (
            "low" if case["category"] in
            ["insufficient_data", "conflicting_data", "sensor_quality"]
            else "moderate"
        )
    }

    return {
        "id": f"SYN-{split.upper()}-{number:05d}",
        "source_type": "synthetic",
        "scenario_category": case["category"],
        "prompt": prompt,
        "response": response
    }

def write_jsonl(filename, count, split, start):
    path = ROOT / filename

    with path.open("w", encoding="utf-8") as file:
        for i in range(count):
            record = make_record(start + i, split)
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Created {path}: {count} records")

write_jsonl("train.jsonl", 1200, "train", 1)
write_jsonl("validation.jsonl", 150, "validation", 1201)
write_jsonl("test.jsonl", 150, "test", 1351)

print("Dataset generation completed.")
print("IMPORTANT: These are synthetic examples, not verified plant data.")
