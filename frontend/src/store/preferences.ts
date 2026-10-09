import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { UserPreference } from '../types/api'

const KEY = 'thlpro_preferences'

export const defaultPreferences: UserPreference = {
  selected_asset: 'BOVA11',
  selected_strike: '185',
  expiration_count: 6,
  show_calls: true,
  show_puts: true,
  auto_refresh: true,
  refresh_interval: 5,
  theme: 'dark',
}

export function usePreferences() {
  const [prefs, setPrefs] = useState<UserPreference>(() => {
    const raw = localStorage.getItem(KEY)
    return raw ? { ...defaultPreferences, ...JSON.parse(raw) } : defaultPreferences
  })

  useEffect(() => {
    localStorage.setItem(KEY, JSON.stringify(prefs))
    if (prefs.theme === 'dark') document.documentElement.classList.add('dark')
    else document.documentElement.classList.remove('dark')
  }, [prefs])

  useEffect(() => {
    async function load() {
      try {
        const { data } = await api.get('/users/me/preferences')
        setPrefs((prev) => ({ ...prev, ...data }))
        return
      } catch {
        // endpoint pode não existir no backend atual
      }
      try {
        const { data } = await api.get('/preferences')
        setPrefs((prev) => ({ ...prev, ...data }))
      } catch {
        // fallback local
      }
    }
    load()
  }, [])

  useEffect(() => {
    const body = { ...prefs }
    const timer = window.setTimeout(async () => {
      try {
        await api.put('/users/me/preferences', body)
        return
      } catch {
        // endpoint pode não existir no backend atual
      }
      try {
        await api.put('/preferences', body)
      } catch {
        // fallback local
      }
    }, 300)
    return () => window.clearTimeout(timer)
  }, [prefs])

  return { prefs, setPrefs }
}
