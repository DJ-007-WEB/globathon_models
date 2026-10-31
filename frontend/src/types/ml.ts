// Deterministic ML output contract v2.1.0 (ml-service/configs/output_schema.json).
// Only the fields the UI renders are typed; every number may be null and stays null.

export type AnalysisStatus = "success" | "partial" | "invalid_input" | "failed";
export type ComponentStatus = "available" | "partial" | "unavailable" | "not_applicable";

export interface EnergyComponent {
  value_kwh: number | null;
  status: ComponentStatus;
  source?: string | null;
  completeness?: number | null;
  unit?: string;
  reason?: string | null;
  sign_convention?: string;
}

export interface Waterfall {
  status: "ok" | "warning" | "unavailable";
  reason?: string | null;
  forecast_energy_kwh: number | null;
  expected_energy_kwh: number | null;
  actual_energy_kwh: number | null;
  weather_effect_kwh: number | null;
  plant_effect_kwh: number | null;
  total_deviation_kwh: number | null;
  observed_deviation_kwh: number | null;
  estimated_anomaly_energy_kwh: number | null;
  potentially_recoverable_energy_kwh: number | null;
  reconciled: boolean;
  tolerance_kwh: number | null;
  limitations: string[];
}

export interface QualityCheck {
  check_id: string;
  status: "pass" | "warning" | "fail" | "not_checked";
  count: number;
  message: string;
  affected_devices?: string[];
  time_ranges?: Array<{ start?: string; end?: string }>;
  details?: Record<string, unknown>;
}

export interface DataQuality {
  status: "pass" | "warning" | "fail";
  valid: boolean;
  rows: number;
  checks: QualityCheck[];
  counts: { checks: number; fail: number; warning: number; pass: number; not_checked: number };
  sampling_interval_seconds: number | null;
  limitations: string[];
}

export interface Anomaly {
  timestamp_utc: string | null;
  device_id: string | null;
  status: string;
  checks: string[];
  message: string;
  evidence: Record<string, number | null>;
  missing_evidence: string[];
}

export interface Hypothesis {
  cause: string;
  label: string;
  status: "confirmed_event" | "suspected" | "unresolved";
  root_cause_confirmed: boolean;
  event_confirmed: boolean;
  confidence: number | null;
  interval: { timestamp_utc: string | null; device_id: string | null };
  evidence: string[];
  missing_evidence: string[];
  source: string;
}

export interface DevicePerformance {
  device_id: string;
  row_count?: number;
  actual_energy_kwh: number | null;
  expected_energy_kwh: number | null;
  deviation_kwh: number | null;
}

export interface ColumnMapping {
  input: string;
  source_file: string | null;
  sheet_name: string | null;
  source_column: string;
  canonical_role: string | null;
  device_id: string | null;
  detected_unit: string | null;
  canonical_unit: string | null;
  conversion: string | null;
  confidence: number | null;
  used: boolean;
  reasons: string[];
}

export interface InputRole {
  role: "operating" | "weather" | "devices" | "forecast" | "event_log";
  status: "used" | "unavailable" | "not_supplied";
  source_file: string | null;
  sheet_name: string | null;
  mapped_fields: number;
  unresolved_fields: string[];
  reason: string | null;
  coverage?: number | null;
}

export interface AnomalyRun {
  device_id: string;
  start_utc: string;
  end_utc: string;
  intervals: number;
  checks: string[];
  overlapping_events: string[];
}

export interface Capability { status: "available" | "unavailable" | "not_applicable"; reason: string | null }

export interface MlResult {
  schema_version: string;
  analysis_status: AnalysisStatus;
  analysis_mode: "snapshot" | "full";
  summary: string;
  request: { plant_id: string | null; source_files: string[]; timezone: string | null; interval_minutes: number | null; mode_requested: string };
  interval: {
    start_utc: string | null; end_utc: string | null; timezone: string | null; timestamp_basis?: string;
    duration_minutes: number | null; sampling_interval_seconds: number | null; device_count: number | null; row_count: number | null;
  };
  energy: { forecast: EnergyComponent; expected: EnergyComponent; actual: EnergyComponent; deviation: EnergyComponent };
  device_performance: DevicePerformance[];
  expected_deviation?: EnergyComponent;
  expected_deviation_kwh?: number | null;
  waterfall: Waterfall;
  anomalies: Anomaly[];
  hypotheses: Hypothesis[];
  evidence: string[];
  limitations: string[];
  unresolved_fields: string[];
  missing_required_fields: string[];
  data_quality: DataQuality;
  capabilities: Record<string, Capability>;
  units: Record<string, string>;
  method: string;
  model_status: string;
  errors: Array<{ code: string; message: string; field?: string | null }>;
  column_mapping?: ColumnMapping[];
  input_roles?: InputRole[];
  anomaly_runs?: AnomalyRun[];
}
