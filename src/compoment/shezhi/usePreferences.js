import { createContext, useContext } from 'react'

export const PreferencesContext = createContext(null)

export function usePreferences() {
  const context = useContext(PreferencesContext)
  if (!context) throw new Error('页面需要放在 PreferencesProvider 中')
  return context
}
