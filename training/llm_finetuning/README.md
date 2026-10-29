# Solar Recovery Intelligence — local LLM fine-tuning

This directory contains a supervised fine-tuning (SFT) workflow for adapting Qwen3.5-4B to explain structured solar diagnostics. It does not train a foundation model from scratch. It trains a small LoRA adapter that can later be exported for local inference.

## Hardware guidance

The project's current laptop has an RTX 4050 Laptop GPU with 6 GB VRAM. That is not a suitable target for the recommended Qwen3.5-4B BF16 LoRA recipe: current Unsloth guidance estimates about 10 GB VRAM for Qwen3.5-4B BF16 LoRA. Use a GPU runtime with at least 16 GB VRAM (for example, a compatible Kaggle/Colab GPU) to train, then bring the resulting adapter/export back for local inference. Training in a hosted notebook is only for model training; inference can remain local through Ollama. Confirm the event rules permit your chosen training environment and data handling.

The current Qwen3.5 guidance requires Transformers v5 and does not recommend 4-bit QLoRA for Qwen3.5 because of quantization differences. This recipe uses BF16/16-bit LoRA, not 4-bit QLoRA.

References:
- Unsloth Qwen3.5 fine-tuning guide: https://unsloth.ai/docs/models/qwen3.5/fine-tune
- Official model: https://huggingface.co/Qwen/Qwen3.5-4B

## What fine-tuning should teach

Fine-tune response behavior, not solar facts that should come from a reference system. Training examples should teach the model to:
- preserve supplied findings and numerical values;
- state when the root cause is unknown;
- report conflicting telemetry without arbitrarily choosing a source;
- recommend evidence-gathering checks before repairs;
- never claim to have consulted a reference that was not supplied;
- return the exact JSON response schema used by the application.

Keep calculations, anomaly detection, confidence computation, and intervention ranking in the deterministic/ML pipeline.

## Dataset format

Create local files that are NOT committed to Git:
- data/train.jsonl
- data/validation.jsonl

Each line is one JSON object with a conversational messages array, as shown in examples/train.example.jsonl. Include a system message, a user message containing a structured diagnostic report, and an assistant message containing the desired JSON answer. Every assistant target must be reviewed by a human. Do not use E01-E16 evaluation cases as training examples. Keep a separate held-out evaluation set to avoid leakage.

Start with a small pilot only after you have enough diverse, high-quality examples. Synthetic examples are useful for schema and safety behavior but do not prove real-world solar diagnostic performance. Do not train on invented manufacturer guidance or unverified root-cause labels.

Recommended practical starting point:
- Aim for 100–300 carefully reviewed examples if time allows; quality and diversity matter more than a large noisy set.
- Include both normal and anomalous cases, missing evidence, contradictory sensors, false alarms, unapproved actions, and cases where the correct answer is to say the cause is unknown.
- Keep the train/validation split separated by scenario or source event, not by near-duplicate rows.
- Keep the existing E01-E16 suite as a separate evaluation set.

## Prepare and validate

From this directory, run:
~~~bash
python validate_dataset.py --train data/train.jsonl --validation data/validation.jsonl
~~~

The validator checks JSONL syntax, message roles, and the required output keys. It cannot verify that a target answer is factually correct; a human must review it.

## Train

Run on a supported GPU runtime with a clean Python environment and current Unsloth/Transformers v5:
~~~bash
pip install --upgrade --force-reinstall --no-cache-dir unsloth unsloth_zoo
pip install datasets trl
python train_lora.py --train data/train.jsonl --validation data/validation.jsonl --output outputs/qwen35-solar-lora
~~~

The script uses a short 2,048-token context, batch size 1, gradient accumulation, gradient checkpointing, and two epochs as a conservative baseline. If the run runs out of memory, reduce sequence length to 1,024 first. Do not simply increase epochs to lower training loss; inspect validation loss and held-out behavior.

The output directory contains the LoRA adapter and tokenizer files. Model weights and training outputs are intentionally ignored by Git.

## After training

1. Compare the base model and fine-tuned adapter on the same held-out evaluation set.
2. Report valid JSON rate, unsupported-cause rate, numeric-preservation rate, conflict handling, unsafe recommendation rate, evidence traceability, and latency.
3. Keep the adapter only if it improves the target metrics without regressions.
4. Export to GGUF using a compatible, current Unsloth workflow if Ollama deployment is desired. Test the exported model and chat template before replacing the current local model. The user's currently installed Ollama version is old, so confirm it supports the exported Qwen3.5 artifact before relying on it.
5. Never commit plant/customer data, model weights, credentials, or training logs to this repository.

Fine-tuning is optional. A better prompt, a strict schema, and deterministic validation may outperform a small fine-tune when the dataset is tiny or noisy.