'use client'
/**
 * Renders the official Google Identity Services "Sign in with Google" button.
 *
 * Loads the GIS script once, initializes it with NEXT_PUBLIC_GOOGLE_CLIENT_ID
 * and hands the resulting ID token ("credential") to `onCredential` — the
 * login page exchanges it for an app JWT via POST /auth/google.
 *
 * Renders nothing when NEXT_PUBLIC_GOOGLE_CLIENT_ID is unset, so the login
 * page works unchanged in environments without Google OAuth configured.
 */
import { useEffect, useRef, useState } from 'react'

const CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID
const GSI_SRC = 'https://accounts.google.com/gsi/client'

interface GoogleAccounts {
  accounts: {
    id: {
      initialize: (config: { client_id: string; callback: (r: { credential: string }) => void }) => void
      renderButton: (el: HTMLElement, options: Record<string, unknown>) => void
    }
  }
}

declare global {
  interface Window { google?: GoogleAccounts }
}

function loadGsiScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.google?.accounts?.id) return resolve()
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${GSI_SRC}"]`)
    if (existing) {
      existing.addEventListener('load', () => resolve())
      existing.addEventListener('error', () => reject(new Error('Failed to load Google Sign-In')))
      return
    }
    const script = document.createElement('script')
    script.src = GSI_SRC
    script.async = true
    script.defer = true
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Failed to load Google Sign-In'))
    document.head.appendChild(script)
  })
}

export default function GoogleSignInButton({
  onCredential,
  onError,
}: {
  onCredential: (credential: string) => void
  onError?: (message: string) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!CLIENT_ID || !containerRef.current) return
    let cancelled = false

    loadGsiScript()
      .then(() => {
        if (cancelled || !containerRef.current || !window.google) return
        window.google.accounts.id.initialize({
          client_id: CLIENT_ID,
          callback: (response) => onCredential(response.credential),
        })
        window.google.accounts.id.renderButton(containerRef.current, {
          theme: 'filled_black',
          size: 'large',
          width: 336,
          text: 'continue_with',
          shape: 'pill',
          logo_alignment: 'left',
        })
      })
      .catch((err: Error) => {
        if (cancelled) return
        setFailed(true)
        onError?.(err.message)
      })

    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!CLIENT_ID || failed) return null

  return (
    <div>
      <div className="flex items-center gap-3 my-5">
        <div className="flex-1 h-px bg-white/[0.08]" />
        <span className="text-[11px] text-white/30 uppercase tracking-wider">or</span>
        <div className="flex-1 h-px bg-white/[0.08]" />
      </div>
      <div ref={containerRef} className="flex justify-center min-h-[44px]" />
    </div>
  )
}
