#!/usr/bin/env python3
"""Supervised LoRA fine-tuning for Qwen3.5-4B on structured solar diagnostics.

Run this on a supported GPU runtime; the project's 6 GB laptop GPU is below
the recommended VRAM for Qwen3.5-4B BF16 LoRA.
"""

import argparse
import json
import sys
from pathlib import Path

MODEL_NAME = "Qwen/Qwen3.5-4B"
REQUIRED_KEYS = {
    "confirmed_findings",
    "possible_explanations",
    "recommended_next_checks",
    "limitations",
}


def read_jsonl(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc

            messages = row.get("messages") if isinstance(row, dict) else None
            if not isinstance(messages, list) or len(messages) < 3:
                raise ValueError(
                    f"{path}:{line_number}: expected a messages array with "
                    "system, user, and assistant messages"
                )
            if messages[0].get("role") != "system":
                raise ValueError(f"{path}:{line_number}: first message must be system")
            if messages[-1].get("role") != "assistant":
                raise ValueError(f"{path}:{line_number}: final message must be assistant")
            if not any(m.get("role") == "user" for m in messages):
                raise ValueError(f"{path}:{line_number}: missing user message")

            try:
                target = json.loads(messages[-1].get("content", ""))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"{path}:{line_number}: assistant target must be JSON"
                ) from exc

            if not isinstance(target, dict) or not REQUIRED_KEYS.issubset(target):
                raise ValueError(
                    f"{path}:{line_number}: assistant target must contain "
                    + ", ".join(sorted(REQUIRED_KEYS))
                )

            rows.append({"messages": messages})

    if not rows:
        raise ValueError(f"No valid examples found in {path}")
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("outputs/qwen35-solar-lora"))
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument(
        "--allow-low-vram",
        action="store_true",
        help="Attempt training below the recommended 10 GB VRAM at your own risk.",
    )
    args = parser.parse_args()

    for path in (args.train, args.validation):
        if not path.is_file():
            raise SystemExit(f"Dataset file not found: {path}")

    # Fail early on the current 6 GB laptop instead of likely running out of memory.
    try:
        import torch
    except ImportError as exc:
        raise SystemExit(
            "PyTorch is not installed. Use the documented Unsloth environment."
        ) from exc

    if not torch.cuda.is_available():
        raise SystemExit(
            "CUDA GPU not detected. Run training on a compatible GPU runtime. "
            "Local CPU training for this 4B model is not the recommended path."
        )

    gpu = torch.cuda.get_device_properties(0)
    vram_gb = gpu.total_memory / (1024 ** 3)
    print(f"GPU: {gpu.name}; VRAM: {vram_gb:.1f} GB")
    if vram_gb < 10 and not args.allow_low_vram:
        raise SystemExit(
            "This recipe expects roughly 10 GB VRAM for Qwen3.5-4B BF16 LoRA. "
            f"Detected {vram_gb:.1f} GB. Use a compatible 16 GB GPU runtime, "
            "or explicitly pass --allow-low-vram if you want to risk an OOM."
        )

    train_rows = read_jsonl(args.train)
    validation_rows = read_jsonl(args.validation)
    print(
        f"Loaded {len(train_rows)} training and "
        f"{len(validation_rows)} validation examples."
    )
    print(
        "Reminder: do not use E01-E16 or any held-out evaluation cases "
        "as training data."
    )

    try:
        from datasets import Dataset
        from unsloth import FastLanguageModel
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        raise SystemExit(
            "Missing training dependencies. Install a current Unsloth release, "
            "Transformers v5, datasets, and TRL as documented in this folder."
        ) from exc

    max_seq_length = args.max_seq_length
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model,
        max_seq_length=max_seq_length,
        load_in_4bit=False,
        load_in_16bit=True,
        full_finetuning=False,
    )

    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=3407,
        max_seq_length=max_seq_length,
    )

    def render_rows(rows):
        rendered = []
        for row in rows:
            text = tokenizer.apply_chat_template(
                row["messages"],
                tokenize=False,
                add_generation_prompt=False,
            )
            rendered.append({"text": text})
        return Dataset.from_list(rendered)

    train_dataset = render_rows(train_rows)
    validation_dataset = render_rows(validation_rows)
    use_bf16 = bool(torch.cuda.is_bf16_supported())

    training_args = SFTConfig(
        output_dir=str(args.output),
        max_seq_length=max_seq_length,
        dataset_text_field="text",
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=8,
        num_train_epochs=args.epochs,
        learning_rate=args.learning_rate,
        warmup_ratio=0.05,
        logging_steps=5,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="cosine",
        fp16=not use_bf16,
        bf16=use_bf16,
        seed=3407,
        dataset_num_proc=1,
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        train_dataset=train_dataset,
        eval_dataset=validation_dataset,
        tokenizer=tokenizer,
        args=training_args,
    )

    trainer.train()

    adapter_dir = args.output / "adapter"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    metrics = trainer.evaluate()

    with (args.output / "evaluation_metrics.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(metrics, handle, indent=2)

    print(f"LoRA adapter saved to: {adapter_dir}")
    print(f"Validation metrics saved to: {args.output / 'evaluation_metrics.json'}")
    print(
        "Next: compare base vs adapter on a separate held-out suite. "
        "Do not deploy based on training loss alone."
    )


if __name__ == "__main__":
    main()
