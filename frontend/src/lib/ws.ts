import type { WsMarketEvent } from '../types/api'

interface WsConfig {
  token: string
  onMessage: (event: WsMarketEvent) => void
  onStatus: (status: 'connecting' | 'connected' | 'disconnected') => void
}

export class MarketWsClient {
  private ws: WebSocket | null = null
  private attempts = 0
  private stopped = false
  private config: WsConfig

  constructor(config: WsConfig) {
    this.config = config
  }

  connect() {
    this.stopped = false
    this.config.onStatus('connecting')
    const base = import.meta.env.VITE_WS_URL || `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/market-data`
    const url = `${base}?token=${encodeURIComponent(this.config.token)}`
    this.ws = new WebSocket(url)

    this.ws.onopen = () => {
      this.attempts = 0
      this.config.onStatus('connected')
    }

    this.ws.onmessage = (evt) => {
      try {
        this.config.onMessage(JSON.parse(evt.data) as WsMarketEvent)
      } catch {
        // ignora payload inválido
      }
    }

    this.ws.onclose = () => {
      this.config.onStatus('disconnected')
      if (!this.stopped) this.scheduleReconnect()
    }

    this.ws.onerror = () => {
      this.ws?.close()
    }
  }

  private scheduleReconnect() {
    this.attempts += 1
    const delay = Math.min(15000, 1000 * 2 ** this.attempts)
    window.setTimeout(() => {
      if (!this.stopped) this.connect()
    }, delay)
  }

  stop() {
    this.stopped = true
    this.ws?.close()
    this.ws = null
  }
}
