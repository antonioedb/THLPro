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
  private reconnectTimer: number | null = null
  private config: WsConfig


  constructor(config: WsConfig) {
    this.config = config
  }


  connect() {
    this.clearReconnectTimer()
    this.stopped = false


    if (this.ws) {
      this.ws.onclose = null
      this.ws.onerror = null
      this.ws.onmessage = null
      this.ws.onopen = null
      this.ws.close()
      this.ws = null
    }


    this.config.onStatus('connecting')


    const base =
      import.meta.env.VITE_WS_URL
      || `${
        window.location.protocol === 'https:' ? 'wss' : 'ws'
      }://${window.location.host}/ws/market-data`


    const url = `${base}?token=${encodeURIComponent(this.config.token)}`


    this.ws = new WebSocket(url)


    this.ws.onopen = () => {
      this.attempts = 0
      this.config.onStatus('connected')
    }


    this.ws.onmessage = (event) => {
      try {
        this.config.onMessage(
          JSON.parse(event.data) as WsMarketEvent,
        )
      } catch {
        // Ignora payload inválido.
      }
    }


    this.ws.onclose = () => {
      this.ws = null
      this.config.onStatus('disconnected')


      if (!this.stopped) {
        this.scheduleReconnect()
      }
    }


    this.ws.onerror = () => {
      this.ws?.close()
    }
  }


  private scheduleReconnect() {
    this.clearReconnectTimer()


    this.attempts += 1


    const delay = Math.min(
      15000,
      1000 * 2 ** this.attempts,
    )


    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null


      if (!this.stopped) {
        this.connect()
      }
    }, delay)
  }


  private clearReconnectTimer() {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }


  stop() {
    this.stopped = true
    this.clearReconnectTimer()


    if (this.ws) {
      this.ws.onclose = null
      this.ws.onerror = null
      this.ws.onmessage = null
      this.ws.onopen = null
      this.ws.close()
      this.ws = null
    }
  }
}