import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { useSignIn } from '@/hooks/useAuth'
import { ApiError } from '@/lib/api'

export default function SignIn() {
  const navigate = useNavigate()
  const signIn = useSignIn()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    signIn.mutate({ email, password }, { onSuccess: () => navigate('/', { replace: true }) })
  }

  const err = signIn.error as ApiError | null

  return (
    <AuthLayout title="Sign in" subtitle="Access is invite-only.">
      <form onSubmit={onSubmit} className="space-y-4">
        {err ? (
          <Alert tone="error">
            {err.isColdStart
              ? 'The server is waking up — this can take up to a minute on the free tier. Try again shortly.'
              : err.message}
          </Alert>
        ) : null}

        <Field label="Email" htmlFor="email">
          <Input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>

        <Field label="Password" htmlFor="password">
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>

        <Button type="submit" className="w-full" disabled={signIn.isPending}>
          {signIn.isPending ? <Spinner /> : null}
          Sign in
        </Button>

        <p className="text-muted text-center text-xs">
          Have an invite code?{' '}
          <Link to="/signup" className="text-[var(--accent)] hover:underline">
            Create your account
          </Link>
        </p>
      </form>
    </AuthLayout>
  )
}

export function AuthLayout({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children: React.ReactNode
}) {
  return (
    <div className="flex min-h-full items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm space-y-6">
        <div className="space-y-1.5 text-center">
          <div className="mb-5 flex justify-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--accent)] text-[var(--accent-fg)]">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M3 17l5-5 4 3 8-8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
          </div>
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          <p className="text-muted text-sm">{subtitle}</p>
        </div>
        <div className="surface rounded-lg border p-6">{children}</div>
      </div>
    </div>
  )
}
