// Marketing copy. Every factual statement is verifiable in this repository; the source is noted.
import type { IconName } from "../design/Icon";

export const NAV = [
  { to: "/capabilities", label: "Capabilities" },
  { to: "/trust", label: "Trust" },
  { to: "/demo", label: "Demo" },
  { to: "/resources", label: "Resources" },
  { to: "/about", label: "About" },
  { to: "/contact", label: "Contact" },
];

// backend/main.py upload limits; INTEGRATION_BASELINE.md (raw upload not persisted).
export const FACTS = [
  { label: "File formats", value: "2", body: "CSV and XLSX. One operating-data file per request, plus optional context files." },
  { label: "Upload limit", value: "25 MiB", body: "Default limit, checked before analysis starts." },
  { label: "Source of numbers", value: "ML first", body: "Every figure comes from the deterministic pipeline. The language model never calculates." },
  { label: "Raw files kept", value: "0", body: "The uploaded file is not stored after analysis — only the structured result." },
];

// ml-service/src modules and configs/defaults.yaml values.
export const STAGES = [
  { short: "Read and understand the file", title: "Data ingestion and mapping",
    body: "Reads one CSV or XLSX export, detects the header row, then maps columns to physical roles — timestamp, device, power, energy, irradiance, temperature.",
    input: "Uploaded CSV / XLSX", output: "Mapped table + unresolved fields",
    specs: [["Formats", "CSV, XLSX"], ["Header scan", "First 30 rows"], ["Mapping", "Alias vocabulary, unit normalisation"], ["Ambiguous columns", "Reported, not guessed"]],
    source: "ingestion.py · schema_mapping.py" },
  { short: "Check the data", title: "Data-quality validation",
    body: "Runs deterministic checks for duplicates, ordering, gaps, missing values, night-time generation and implausible readings.",
    input: "Mapped table", output: "Pass / warning / fail per check",
    specs: [["Gap threshold", "1.5 × interval"], ["Min valid fraction", "80% per field"], ["Night screen", "Sun elevation −0.833°"], ["Scoring", "None — counts only"]],
    source: "validation.py" },
  { short: "Model what should happen", title: "Expected-energy baseline",
    body: "Estimates the energy the plant should have produced from measured irradiance and temperature.",
    input: "Irradiance, temperature, capacity", output: "Expected energy (kWh)",
    specs: [["Method", "Physics baseline"], ["Temperature coefficient", "Configured per plant"], ["Basis", "Measured POA irradiance"], ["If inputs missing", "Marked unavailable"]],
    source: "baseline.py" },
  { short: "Find unusual intervals", title: "Anomaly detection",
    body: "Flags intervals where output falls short of the baseline or deviates from peer devices, with persistence and CUSUM checks.",
    input: "Actual vs expected", output: "Alert intervals",
    specs: [["Shortfall threshold", "20% below expected"], ["Min irradiance", "50 W/m²"], ["Peer check", "≥ 3 same-time devices"], ["Meaning", "Unusual, not a cause"]],
    source: "anomaly.py" },
  { short: "Propose explanations", title: "Attribution of alert intervals",
    body: "Rules attach possible contributing factors to each alert interval, listing the evidence found and the evidence still missing.",
    input: "Alert intervals + evidence", output: "Unconfirmed hypotheses",
    specs: [["Source", "Deterministic rules"], ["Low-output ratio", "< 0.80"], ["Status", "Suspected until confirmed"], ["Confirmation", "Event log or inspection"]],
    source: "attribution.py" },
  { short: "Reconcile the gap", title: "Energy waterfall",
    body: "Splits the forecast-to-actual difference into a weather effect and a plant effect that reconcile exactly.",
    input: "Forecast, expected, actual", output: "Two-effect waterfall",
    specs: [["Steps", "Forecast → Expected → Actual"], ["Effects", "Weather, plant"], ["Tolerance", "10⁻⁶ kWh"], ["Missing forecast", "Shown as unavailable"]],
    source: "counterfactual.py" },
  { short: "Explain in plain language", title: "AI-generated explanation",
    body: "A locally hosted language model writes a structured narrative from the saved ML result and answers report-grounded questions.",
    input: "Saved ML result", output: "Narrative + follow-up answers",
    specs: [["Runs", "Locally (fine-tuned Qwen LoRA)"], ["Calculates", "Nothing"], ["If unavailable", "Report still saved"], ["Confidence", "Stated, never scored"]],
    source: "llm-service" },
];

export interface Capability { slug: string; icon: IconName; title: string; body: string; bullets: string[]; image: string }
export const CAPABILITIES: Capability[] = [
  { slug: "ingestion", icon: "file-in", title: "Data ingestion and mapping", image: "/images/switchgear-panel.jpg",
    body: "Upload the export your monitoring system already produces. Columns are mapped to physical roles automatically.",
    bullets: ["CSV and XLSX, with optional weather, forecast and device files", "Header, units-row and encoding detection", "Unmapped columns listed as unresolved"] },
  { slug: "validation", icon: "shield-check", title: "Data-quality validation", image: "/images/switchgear-room.jpg",
    body: "Deterministic checks show whether the data can support the analysis before anyone relies on the numbers.",
    bullets: ["Duplicates, ordering, gaps, missing values", "Night-time generation screening", "Affected devices and time ranges"] },
  { slug: "baseline", icon: "baseline", title: "Expected-energy baseline", image: "/images/pv-landscape.jpg",
    body: "A physics baseline estimates what the plant should have produced under the weather it actually saw.",
    bullets: ["Measured irradiance and temperature", "Configured temperature coefficient", "Unavailable when inputs are missing"] },
  { slug: "waterfall", icon: "waterfall", title: "Energy waterfall", image: "/images/pv-topdown.jpg",
    body: "Forecast, weather effect, expected, plant effect and actual — one reconciled view of where the energy went.",
    bullets: ["Two effects that reconcile exactly", "Signed values in kWh", "Null components shown, never zero-filled"] },
  { slug: "anomalies", icon: "pulse", title: "Anomalies and hypotheses", image: "/images/pylon-dusk.jpg",
    body: "Unusual intervals are flagged and paired with rule-based hypotheses that state their evidence and their gaps.",
    bullets: ["Shortfall, peer and persistence checks", "Hypotheses marked unconfirmed", "Missing evidence listed explicitly"] },
  { slug: "ai", icon: "sparkle", title: "Local AI explanation", image: "/images/dusk-field.jpg",
    body: "A locally hosted model turns the result into readable observations, possible causes and checks — and answers follow-ups.",
    bullets: ["Grounded in the saved report", "Never the source of a number", "Report survives if the model is down"] },
];

export const PRINCIPLES = [
  { title: "ML is the authority", body: "Numbers come from the deterministic service. The AI explains them and cannot change them." },
  { title: "Hypotheses are not faults", body: "Rules propose likely contributing factors with evidence. A person must confirm them on the plant." },
  { title: "Unknown stays unknown", body: "Missing values stay empty. Ambiguous units are reported, not guessed." },
];

export const AUDIENCES = [
  { title: "Asset managers", body: "A reconciled view of forecast versus delivered energy, split into weather and plant effects, for performance reviews." },
  { title: "Plant operators", body: "A short list of unusual intervals and the checks worth running on site, without reading raw exports line by line." },
  { title: "Performance analysts", body: "Validation detail, mapped roles and evidence behind every flag, so the method can be challenged." },
  { title: "Technical reviewers", body: "Clear separation between measured facts, rule-based hypotheses and AI narrative." },
];

// README.md, backend/main.py and the LLM fallback behaviour.
export const FAQ = [
  { question: "What file can I upload?", answer: "One CSV or XLSX operating-data export per analysis, up to 25 MiB by default, with optional weather, forecast, device and event-log files. It should contain timestamps, a device identifier and power or interval energy. Irradiance and temperature enable the expected-energy baseline; a forecast completes the waterfall." },
  { question: "Does the AI calculate the numbers?", answer: "No. Every energy value, check result, anomaly and hypothesis comes from the deterministic ML service. The local language model reads that result and explains it; it cannot add or change figures." },
  { question: "What happens if the AI model is unavailable?", answer: "The analysis still completes and the report is saved with the full deterministic result. The explanation is clearly labelled as an evidence-only fallback instead of AI narrative." },
  { question: "Is my raw file stored?", answer: "No. The uploaded file is processed and discarded. The structured analysis result and its explanation are stored in your workspace so you can reopen the report." },
  { question: "What does “hypothesis” mean here?", answer: "A rule-based possible contributing factor attached to an alert interval, with the evidence found and the evidence still missing. It stays unconfirmed until an event log or a site inspection confirms it." },
  { question: "What can SolarSleuth not do yet?", answer: "It does not connect to live SCADA feeds, does not export PDF reports (use the browser's print), does not quantify recoverable energy without explicit operational evidence, and does not edit or delete plants from the browser." },
];

// Each statement is tagged with the file it comes from.
export const LIMITS = [
  { text: "Alerts indicate unusual behaviour, not root causes.", source: "ML output contract" },
  { text: "Recoverable energy is not guaranteed without operational evidence.", source: "Waterfall limitations" },
  { text: "Peer checks need at least three comparable devices.", source: "Anomaly configuration" },
  { text: "The ML result is saved unchanged.", source: "Integration baseline" },
  { text: "Night-time screening is an approximation for flagging, not proof.", source: "Validation configuration" },
  { text: "No live SCADA connection. Files are uploaded per analysis.", source: "Backend upload contract" },
  { text: "Confidence is stated by the model, never computed as a score.", source: "LLM output contract" },
  { text: "Missing forecast data leaves the waterfall incomplete — not zero.", source: "Waterfall contract" },
];

export const CAN = [
  "Validate the structure and quality of an uploaded export",
  "Estimate expected energy from measured irradiance and temperature",
  "Split forecast-to-actual deviation into weather and plant effects",
  "Flag unusual intervals and attach rule-based hypotheses with evidence",
  "Explain the saved result in plain language with a local model",
];
export const CANNOT = [
  "Confirm a physical root cause without event logs or inspection",
  "Guarantee that lost energy is recoverable",
  "Fill in missing values or guess ambiguous units",
  "Connect to live SCADA feeds",
  "Export PDF reports (browser print is available)",
];

export const DATA_HANDLING = [
  { value: "2", title: "File formats.", body: "CSV and XLSX. One operating-data file per request." },
  { value: "25 MiB", title: "Upload limit.", body: "Default limit, checked before analysis starts." },
  { value: "ML first", title: "Source of numbers.", body: "Every figure comes from the deterministic pipeline. The language model never calculates." },
  { value: "0", title: "Raw files kept.", body: "The uploaded file is not stored after analysis — only the structured result." },
  { value: "Tokens", title: "Sessions.", body: "Workspaces use expiring backend-issued tokens; plants and reports are scoped to one business." },
];

export interface ResourceDoc { slug: string; title: string; icon: IconName; items: string[] }
export const RESOURCES: ResourceDoc[] = [
  { slug: "data-requirements", title: "Data requirements", icon: "book", items: [
    "A timestamp column and a device or inverter identifier — wide layouts with one column per inverter are supported.",
    "AC power (kW) or interval energy (kWh) per device. A units row under the header is read automatically.",
    "Plane-of-array irradiance (W/m²) and module or ambient temperature (°C) enable the expected-energy baseline.",
    "A forecast (energy or AC power) completes the waterfall; without it the forecast step is shown as unavailable.",
    "One CSV or XLSX operating file per analysis, up to 25 MiB by default, plus optional weather, forecast, device and event-log files. Workbook companion sheets are detected by content.",
  ] },
  { slug: "how-it-works", title: "How it works", icon: "layers", items: STAGES.map((stage, index) => `${index + 1}. ${stage.title} — ${stage.body}`) },
  { slug: "method-and-limits", title: "Method and limits", icon: "shield", items: [
    "The waterfall has exactly two effects: weather (forecast → expected) and plant (expected → actual). They reconcile within 10⁻⁶ kWh.",
    "Anomaly checks compare actual output with the physics baseline and with peer devices when at least three are comparable.",
    "Hypotheses come from deterministic rules. They list evidence and missing evidence and are never marked confirmed without it.",
    "Confidence in AI text is stated by the model; SolarSleuth does not compute a confidence score.",
    "Null values are preserved end to end and are never replaced by zero.",
  ] },
];
