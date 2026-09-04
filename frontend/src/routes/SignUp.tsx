import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { useSignUp } from '@/hooks/useAuth'
import type { ApiError } from '@/lib/api'
import { AuthLayout } from './SignIn'

export default function SignUp() {
  const navigate = useNavigate()
  const signUp = useSignUp()
  const [form, setForm] = useState({
    invite_code: '',
    email: '',
    display_name: '',
    password: '',
  })

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    signUp.mutate(form, { onSuccess: () => navigate('/', { replace: true }) })
  }

  const err = signUp.error as ApiError | null

  return (
    <AuthLayout title="Create your account" subtitle="You'll need an invite code.">
      <form onSubmit={onSubmit} className="space-y-4">
        {err ? <Alert tone="error">{err.message}</Alert> : null}

        <Field label="Invite code" htmlFor="invite_code">
          <Input
            id="invite_code"
            required
            value={form.invite_code}
            onChange={set('invite_code')}
            className="font-mono"
          />
        </Field>

        <Field label="Name" htmlFor="display_name">
          <Input id="display_name" required value={form.display_name} onChange={set('display_name')} />
        </Field>

        <Field label="Email" htmlFor="email">
          <Input id="email" type="email" autoComplete="email" required value={form.email} onChange={set('email')} />
        </Field>

        <Field
          label="Password"
          htmlFor="password"
          hint="At least 10 characters, mixing letters with numbers or symbols."
        >
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={10}
            value={form.password}
            onChange={set('password')}
          />
        </Field>

        <Button type="submit" className="w-full" disabled={signUp.isPending}>
          {signUp.isPending ? <Spinner /> : null}
          Create account
        </Button>

        <p className="text-muted text-center text-xs">
          Already have an account?{' '}
          <Link to="/signin" className="text-[var(--accent)] hover:underline">
            Sign in
          </Link>
        </p>
      </form>
    </AuthLayout>
  )
}
