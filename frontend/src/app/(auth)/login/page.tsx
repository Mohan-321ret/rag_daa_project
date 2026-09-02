'use client'
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { motion } from 'framer-motion'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Eye, EyeOff, Brain, ArrowRight, Loader2 } from 'lucide-react'
import { useAppStore } from '@/store/appStore'
import { authApi, setToken, ApiError, type TokenResponse } from '@/lib/api'
import GoogleSignInButton from '@/components/shared/GoogleSignInButton'

const schema = z.object({
  fullName: z.string().optional(),
  email: z.string().email('Invalid email address'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
})
type FormData = z.infer<typeof schema>

export default function LoginPage() {
  const router = useRouter()
  const { setAuthenticated, setCurrentUser } = useAppStore()
  const [showPass, setShowPass] = useState(false)
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [error, setError] = useState<string | null>(null)

  const { register, handleSubmit, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema),
  })

  const completeLogin = (result: TokenResponse) => {
    setToken(result.access_token)
    setCurrentUser({
      name: result.user.full_name || result.user.email.split('@')[0],
      email: result.user.email,
      role: result.user.role,
    })
    setAuthenticated(true)
    router.push('/dashboard')
  }

  const onSubmit = async (data: FormData) => {
    setLoading(true)
    setError(null)
    try {
      const result = mode === 'login'
        ? await authApi.login(data.email, data.password)
        : await authApi.register(data.email, data.password, data.fullName || undefined)
      completeLogin(result)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const onGoogleCredential = async (credential: string) => {
    setLoading(true)
    setError(null)
    try {
      completeLogin(await authApi.google(credential))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Google sign-in failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#080810] flex items-center justify-center p-4 relative overflow-hidden">
      {/* Background */}
      <div className="absolute inset-0">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-blue-600/10 rounded-full blur-3xl" />
        <div className="absolute bottom-1/4 right-1/4 w-96 h-96 bg-violet-600/10 rounded-full blur-3xl" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-cyan-600/5 rounded-full blur-3xl" />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="relative w-full max-w-md"
      >
        {/* Logo */}
        <div className="text-center mb-8">
          <motion.div
            initial={{ scale: 0.8 }}
            animate={{ scale: 1 }}
            transition={{ duration: 0.5, type: 'spring' }}
            className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-500 to-violet-600 mb-4 shadow-2xl shadow-blue-500/25"
          >
            <Brain className="w-7 h-7 text-white" />
          </motion.div>
          <h1 className="text-2xl font-bold text-white">DAA-RAG Platform</h1>
          <p className="text-sm text-white/40 mt-1">Enterprise Knowledge Intelligence</p>
        </div>

        {/* Card */}
        <div className="bg-white/[0.03] border border-white/[0.08] rounded-2xl p-8 backdrop-blur-xl">
          <div className="flex items-center gap-1 bg-white/[0.03] border border-white/[0.07] rounded-xl p-1 mb-6">
            {(['login', 'register'] as const).map(m => (
              <button key={m} type="button" onClick={() => { setMode(m); setError(null) }}
                className={`flex-1 py-1.5 rounded-lg text-xs font-medium capitalize transition-all ${mode === m ? 'bg-blue-600 text-white' : 'text-white/40 hover:text-white/70'}`}>
                {m === 'login' ? 'Sign In' : 'Create Account'}
              </button>
            ))}
          </div>

          {error && (
            <div className="mb-4 px-3 py-2.5 rounded-xl bg-red-500/10 border border-red-500/20 text-xs text-red-400">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            {mode === 'register' && (
              <div>
                <label className="text-xs font-medium text-white/60 mb-1.5 block">Full name</label>
                <input
                  {...register('fullName')}
                  type="text"
                  placeholder="Sarah Chen"
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-4 py-2.5 text-sm text-white placeholder:text-white/20 outline-none focus:border-blue-500/50 focus:bg-white/[0.06] transition-all"
                />
              </div>
            )}

            <div>
              <label className="text-xs font-medium text-white/60 mb-1.5 block">Email address</label>
              <input
                {...register('email')}
                type="email"
                placeholder="sarah.chen@enterprise.com"
                className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-4 py-2.5 text-sm text-white placeholder:text-white/20 outline-none focus:border-blue-500/50 focus:bg-white/[0.06] transition-all"
              />
              {errors.email && <p className="text-[11px] text-red-400 mt-1">{errors.email.message}</p>}
            </div>

            <div>
              <label className="text-xs font-medium text-white/60 mb-1.5 block">Password</label>
              <div className="relative">
                <input
                  {...register('password')}
                  type={showPass ? 'text' : 'password'}
                  placeholder="••••••••••••"
                  className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl px-4 py-2.5 text-sm text-white placeholder:text-white/20 outline-none focus:border-blue-500/50 focus:bg-white/[0.06] transition-all pr-10"
                />
                <button type="button" onClick={() => setShowPass(!showPass)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60 transition-colors">
                  {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              {errors.password && <p className="text-[11px] text-red-400 mt-1">{errors.password.message}</p>}
            </div>

            <motion.button
              type="submit"
              disabled={loading}
              whileHover={{ scale: 1.01 }}
              whileTap={{ scale: 0.99 }}
              className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-gradient-to-r from-blue-600 to-violet-600 text-sm font-semibold text-white hover:from-blue-500 hover:to-violet-500 transition-all disabled:opacity-60 disabled:cursor-not-allowed shadow-lg shadow-blue-500/20"
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <>{mode === 'login' ? 'Sign In' : 'Create Account'} <ArrowRight className="w-4 h-4" /></>}
            </motion.button>
          </form>

          <GoogleSignInButton onCredential={onGoogleCredential} />
        </div>

        <p className="text-center text-[11px] text-white/25 mt-6">
          Enterprise Knowledge Intelligence Platform
        </p>
      </motion.div>
    </div>
  )
}
