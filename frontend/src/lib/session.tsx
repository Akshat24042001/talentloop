import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from './api'

export interface Me {
  user: { id: string; email: string; name: string }
  org: { id: string; name: string; slug: string; settings: Record<string, any> } | null
  role: string | null; role_label: string; platform_admin: boolean
  memberships: { org_id: string; name: string; slug: string; role: string }[]
  can: { manage_team: boolean; manage_jobs: boolean; see_all: boolean }
}

const Ctx = createContext<{ me: Me | null | undefined; refresh: () => Promise<Me | null>; setMe: (m: Me | null) => void }>({
  me: undefined, refresh: async () => null, setMe: () => {},
})

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null | undefined>(undefined)     // undefined = loading, null = signed out
  const refresh = useCallback(async () => {
    try { const m = await api<Me>('/api/auth/me', { quiet401: true }); setMe(m); return m } catch { setMe(null); return null }
  }, [])
  useEffect(() => { refresh() }, [refresh])
  return <Ctx.Provider value={{ me, refresh, setMe }}>{children}</Ctx.Provider>
}
export const useSession = () => useContext(Ctx)
export function useMe(): Me { return useContext(Ctx).me! }

export async function signOut() {
  try { await api('/api/auth/logout', { method: 'POST' }) } catch { /* already signed out */ }
  location.href = '/login'
}
