export type MetricKind = "money" | "count" | "pct" | "number" | "days";

export interface MetricDef {
  id: string;
  label: string;
  description: string;
  kind: MetricKind;
  financial: boolean;
  additive: boolean;
  rate: boolean;
  higher_is_better: boolean | null;
  formula: string;
  synonyms: string[];
}

export interface DimensionDef {
  id: string;
  label: string;
  kind: string;
  time_grain: boolean;
  rollup: boolean;
  order: string[] | null;
}

export interface ScopeInfo {
  scope_key: string;
  label: string;
  badges: string[];
  financial: boolean;
  pii: "raw" | "pseudonym";
  company_totals: boolean;
  locked_filters: Partial<Record<"regions" | "categories", string[]>>;
  regions: string[];
  categories: string[];
}

export interface NavItem {
  id: string;
  label: string;
  path: string;
}

export interface Me {
  user: { id: number; username: string; display_name: string; role: string; role_label: string; region: string | null; category: string | null };
  scope: ScopeInfo;
  fingerprint: string;
  capabilities: string[];
  pages: string[];
  navigation: NavItem[];
  landing: string;
  visible_columns: string[];
  allowed_metrics: string[];
  metrics: MetricDef[];
  data: { dataset: string | null; data_version: string | null; rows: number | null; min_date: string | null; max_date: string | null };
  demo_mode: boolean;
  replica: string;
}

export interface Filters {
  years?: number[];
  quarters?: number[];
  months?: number[];
  year_months?: string[];
  date_from?: string;
  date_to?: string;
  regions?: string[];
  countries?: string[];
  categories?: string[];
  sub_categories?: string[];
  products?: string[];
  segments?: string[];
  genders?: string[];
  statuses?: string[];
  shipping_methods?: string[];
  payment_methods?: string[];
  discount_bands?: string[];
  price_bands?: string[];
  shipping_days_bands?: string[];
}

export type CompareMode = "none" | "prior_year_lfl" | "prior_period";

export interface QuerySpec {
  metrics: string[];
  group_by?: string[];
  time_grain?: string | null;
  filters?: Filters;
  compare?: CompareMode;
  sort_by?: string | null;
  sort_dir?: "asc" | "desc" | null;
  limit?: number;
  include_totals?: boolean;
}

export interface ColumnMeta {
  key: string;
  label: string;
  role: "dim" | "metric";
  kind: string;
  financial?: boolean;
  higher_is_better?: boolean | null;
  rate?: boolean;
}

export type Row = Record<string, string | number | null>;

export interface QueryResult {
  spec: QuerySpec;
  columns: ColumnMeta[];
  rows: Row[];
  totals: Row | null;
  source: string;
  totals_source: string | null;
  compare: { mode: CompareMode; label: string; prior_filters: Filters; source: string } | null;
  notes: string[];
  data_version: string;
  elapsed_ms: number;
  cache?: boolean;
  error?: { code: string; message: string };
}

export interface Kpi {
  id: string;
  label: string;
  kind: MetricKind;
  description: string;
  financial: boolean;
  higher_is_better: boolean | null;
  value: number | null;
  n: number | null;
  prior: number | null;
  delta: number | null;
  pct: number | null;
  spark: { x: string | number; y: number | null }[];
}

export interface KpiResponse {
  kpis: Kpi[];
  compare: string | null;
  notes: string[];
}

export interface PeriodPreset {
  id: string;
  label: string;
  date_from: string | null;
  date_to: string | null;
}

export interface Catalog {
  regions: { name: string; countries: string[] }[];
  countries: string[];
  categories: { name: string; sub_categories: { name: string; products: string[] }[] }[];
  sub_categories: string[];
  products: string[];
  segments: string[];
  genders: string[];
  statuses: string[];
  shipping_methods: string[];
  payment_methods: string[];
  discount_bands: string[];
  price_bands: string[];
  shipping_days_bands: string[];
  years: number[];
  date_range: { min: string; max: string };
  today: string;
  periods: PeriodPreset[];
  locked: Partial<Record<"regions" | "categories", string[]>>;
  rows: number;
  dataset: string;
  data_version: string;
}

export interface Insight {
  id: string;
  title: string;
  text: string;
  value: number;
  spec: QuerySpec;
  financial: boolean;
}

export interface DataNote {
  id: string;
  title: string;
  text: string;
  evidence: string[];
  financial: boolean;
}

export interface OrdersPage {
  columns: { key: string; label: string; kind: string; in_table: boolean }[];
  rows: Row[];
  next_cursor: { order_date: string; order_id: string } | null;
  total: number | null;
  hidden_columns: string[];
}

export interface OrderDetail {
  order: Row;
  fields: { key: string; label: string; kind: string; description: string }[];
  hidden_fields: { key: string; label: string }[];
  pseudonym: boolean;
}

export interface CompareResponse {
  a: { label: string; filters: Filters };
  b: { label: string; filters: Filters };
  kpis: { metric: string; label: string; kind: MetricKind; a: number | null; b: number | null; delta: number | null; pct: number | null; higher_is_better: boolean | null; a_n: number | null; b_n: number | null }[];
  breakdown: Row[] | null;
  trends: { a: Row[]; b: Row[] } | null;
}

export interface DistributionResponse {
  field: string;
  group_by: string | null;
  groups: { group: string; n: number; min: number; q1: number; median: number; q3: number; max: number; mean: number }[];
  histogram: { from: number; to: number; n: number }[];
}
