import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../store/auth'

export default function LoginPage() {
  const { login, user, loading } = useAuth()
  const [email, setEmail] = useState('admin@thlpro.local')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (loading) return <div className="center-screen">Carregando...</div>
  if (user) return <Navigate to="/" replace />

  return (
    <div className="center-screen">
      <form
        className="panel w-full max-w-md space-y-4"
        onSubmit={async (e) => {
          e.preventDefault()
          setSubmitting(true)
          setError('')
          try {
            await login({ email, password })
          } catch (err: any) {
            setError(err?.response?.data?.detail || 'Falha no login. Tente novamente.')
          } finally {
            setSubmitting(false)
          }
        }}
      >
        <h1 className="text-2xl font-bold">Entrar no THLPro</h1>
        <div>
          <label className="label">E-mail</label>
          <input className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div>
          <label className="label">Senha</label>
          <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        {error && <p className="text-sm text-rose-500">{error}</p>}
        <button disabled={submitting} className="btn-primary w-full">
          {submitting ? 'Entrando...' : 'Entrar'}
        </button>
      </form>
    </div>
  )
}
