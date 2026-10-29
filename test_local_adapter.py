
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel

BASE_MODEL = "Qwen/Qwen3.5-0.8B"
ADAPTER_PATH = "models/solar-qwen-lora-final"

print("Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(ADAPTER_PATH)

print("Loading base model...")
dtype = (
    torch.bfloat16
    if torch.cuda.is_bf16_supported()
    else torch.float16
)

base_model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    torch_dtype=dtype,
    device_map="auto",
    low_cpu_mem_usage=True,
)

print("Loading trained LoRA adapter...")
model = PeftModel.from_pretrained(
    base_model,
    ADAPTER_PATH,
)
model.eval()

system_prompt = (
    "You are a solar plant analysis assistant. Separate observations "
    "from possible explanations. Do not invent evidence or claim "
    "certainty without support. Return a valid JSON object with these "
    "fields: summary, observations, possible_causes, "
    "supporting_evidence, recommended_checks, limitations, confidence."
)

user_prompt = (
    "Analyse this solar plant performance case. Separate observations "
    "from possible explanations, avoid unsupported conclusions, and "
    "recommend relevant next checks.\n\n"
    "Plant observations: At 11:30, a 500 kW solar plant produces "
    "310 kW. Irradiance is 720 W/m². Inverter INV-02 reports normal "
    "operation, but its output is 35% lower than comparable inverters. "
    "No maintenance record or fault code is available."
)

messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": user_prompt},
]

inputs = tokenizer.apply_chat_template(
    messages,
    tokenize=True,
    add_generation_prompt=True,
    return_dict=True,
    return_tensors="pt",
)

device = model.get_input_embeddings().weight.device
inputs = {key: value.to(device) for key, value in inputs.items()}

print("Generating response...")
with torch.no_grad():
    outputs = model.generate(
        **inputs,
        max_new_tokens=250,
        do_sample=False,
        pad_token_id=tokenizer.eos_token_id,
    )

prompt_length = inputs["input_ids"].shape[-1]
response = tokenizer.decode(
    outputs[0][prompt_length:],
    skip_special_tokens=True,
)

print("\nMODEL RESPONSE:\n")
print(response)
