export type UserRole = 'admin' | 'user'

export interface LoginRequest {
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in_seconds: number
}

export interface MeResponse {
  id: number
  name: string
  email: string
  role: UserRole
  active: boolean
}

export interface Asset {
  id: number
  symbol: string
  name: string
  asset_type: string
  market: string
  enabled: boolean
  tick_min: string
  strike_interval: string
  lower_range_percent: string
  upper_range_percent: string
  rtd_identifier_pattern: string
  source: string
}

export interface StrikeCoverage {
  strike: string

  // Quantidade total de vencimentos mensais usados na curva.
  monthly_expirations: number

  // Em quantos vencimentos há uma CALL ativa para esse strike.
  call_expirations: number

  // Em quantos vencimentos há uma PUT ativa para esse strike.
  put_expirations: number

  // Em quantos vencimentos há CALL e PUT simultaneamente.
  complete_pairs: number

  // Datas mensais nas quais existe ao menos uma série ativa para o strike.
  monthly_dates: string[]
}

export interface StrikeListResponse {
  asset: string
  spot_price: string | null
  range_low: string | null
  range_high: string | null

  // Mantido para compatibilidade. O backend agora ordena os strikes pela
  // melhor cobertura de CALL + PUT nos vencimentos mensais.
  strikes: string[]

  // Cobertura detalhada de cada strike na curva mensal.
  strike_coverage: StrikeCoverage[]

  // Datas mensais usadas para calcular a cobertura.
  monthly_expirations: string[]

  // Strike mais próximo do spot com CALL + PUT em todos os vencimentos
  // mensais; quando não houver cobertura completa, é o de maior cobertura.
  recommended_strike: string | null

  data_avail: boolean
  warning?: string | null
}

export interface SpotResponse {
  asset: string
  spot_price: string | null
  quote_timestamp?: string
  received_at?: string
  data_status?: string
  message?: string
}

export interface ByStrikeItem {
  expiration_date: string
  option_type: 'CALL' | 'PUT'
  requested_strike: string
  matched_strike: string | null
  tolerance_applied: string | null
  option_symbol: string | null
  status?: string
}

export interface ByStrikeResponse {
  asset: string
  items: ByStrikeItem[]
}

export interface QuoteLatestResponse {
  asset: string
  option_symbol: string
  last_price?: string | null
  bid?: string | null
  ask?: string | null
  premium?: string | null
  quote_timestamp?: string
  received_at?: string
  data_status?: string
  message?: string
}

export interface ClientStatusItem {
  id: number
  client_name: string
  computer_name: string
  connected: boolean
  last_seen_at: string | null
  last_error: string | null
}

export interface SyncSummary {
  created: number
  updated: number
  deactivated: number
  errors: string[]
}

export interface SystemSetting {
  key: string
  value: Record<string, unknown>
  description: string
  updated_at: string
}

export interface AdminLog {
  id: number
  event_type: string
  message: string
  payload_summary: string | null
  client_id: number | null
  user_id: number | null
  created_at: string
}

export interface UserOut {
  id: number
  name: string
  email: string
  role: UserRole
  active: boolean
  created_at: string
  updated_at: string
}

export interface UserPreference {
  selected_asset: string
  selected_strike: string
  expiration_count: number
  show_calls: boolean
  show_puts: boolean
  auto_refresh: boolean
  refresh_interval: number
  theme: 'light' | 'dark'
}

export interface WsMarketEvent {
  type: 'quote' | 'snapshot' | 'status'
  data?: Array<Record<string, unknown>> | Record<string, unknown>
  message?: string
}