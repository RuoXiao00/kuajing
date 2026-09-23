import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { DEFAULT_PREFERENCES, normalizePreferences, PREFERENCES_KEY, readPreferences, writePreferences } from './preferences'
import { PreferencesContext } from './usePreferences'

export function PreferencesProvider({ children }) {
  const [state, setState] = useState(readPreferences)
  const latest = useRef(state.settings)
  const updatePreferences = useCallback((patch) => {
    // 所有页面共享这一份状态：保存昵称会立即更新侧栏，开关变化也无需刷新。
    const settings = normalizePreferences({ ...latest.current, ...patch })
    const warning = writePreferences(settings)
    latest.current = settings
    setState({ settings, warning })
    return !warning
  }, [])
  const resetPreferences = useCallback(() => updatePreferences(DEFAULT_PREFERENCES), [updatePreferences])

  useEffect(() => {
    // storage 事件只由其他标签页触发；同步偏好但不再写回，避免相互触发循环。
    const sync = (event) => {
      if (event.key !== PREFERENCES_KEY && event.key !== null) return
      const next = readPreferences()
      latest.current = next.settings
      setState(next)
    }
    window.addEventListener('storage', sync)
    return () => window.removeEventListener('storage', sync)
  }, [])

  const value = useMemo(() => ({ preferences: state.settings, storageWarning: state.warning,
    updatePreferences, resetPreferences }), [state, updatePreferences, resetPreferences])
  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>
}
