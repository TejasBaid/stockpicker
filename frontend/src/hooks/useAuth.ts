import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, authApi, type User } from '@/lib/api'

const ME_KEY = ['auth', 'me'] as const

export function useCurrentUser() {
  return useQuery<User | null>({
    queryKey: ME_KEY,
    queryFn: async () => {
      try {
        return await authApi.me()
      } catch (err) {
        // 401 is the normal signed-out state, not a failure worth retrying.
        if (err instanceof ApiError && err.status === 401) return null
        throw err
      }
    },
    retry: (count, err) => !(err instanceof ApiError && err.status === 401) && count < 2,
    staleTime: 60_000,
  })
}

export function useSignIn() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      authApi.signIn(email, password),
    onSuccess: (user) => qc.setQueryData(ME_KEY, user),
  })
}

export function useSignUp() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: authApi.signUp,
    onSuccess: (user) => qc.setQueryData(ME_KEY, user),
  })
}

export function useSignOut() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: authApi.signOut,
    onSuccess: () => {
      qc.setQueryData(ME_KEY, null)
      qc.clear()
    },
  })
}
