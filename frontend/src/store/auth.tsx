import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { api, setUnauthorizedHandler, tokenStore } from '../lib/api'
import type { LoginRequest, MeResponse, TokenResponse } from '../types/api'

interface AuthContextValue {
  user: MeResponse | null
  token: string | null
  loading: boolean
  login: (payload: LoginRequest) => Promise<void>
  logout: () => Promise<void>
  refreshMe: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(tokenStore.get())
  const [user, setUser] = useState<MeResponse | null>(null)
  const [loading, setLoading] = useState(true)

  const clearSession = () => {
    tokenStore.clear()
    setToken(null)
    setUser(null)
  }

  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearSession()
    })
  }, [])

  const refreshMe = async () => {
    if (!tokenStore.get()) {
      setLoading(false)
      return
    }
    try {
      const { data } = await api.get<MeResponse>('/auth/me')
      setUser(data)
    } catch {
      clearSession()
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refreshMe()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const login = async (payload: LoginRequest) => {
    const { data } = await api.post<TokenResponse>('/auth/login', payload)
    tokenStore.set(data.access_token)
    setToken(data.access_token)
    await refreshMe()
  }

  const logout = async () => {
    try {
      await api.post('/auth/logout')
    } catch {
      // ignora falha de logout remoto
    }
    clearSession()
  }

  const value = useMemo(
    () => ({ user, token, loading, login, logout, refreshMe }),
    [user, token, loading],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth deve ser usado dentro de AuthProvider')
  return ctx
}
