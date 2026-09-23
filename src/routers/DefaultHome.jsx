import { Navigate } from 'react-router-dom'
import { usePreferences } from '../compoment/shezhi/usePreferences'

export default function DefaultHome() {
  const { preferences } = usePreferences()
  // 仅根地址使用首页偏好，刷新具体页面仍停留在原页面。
  return <Navigate to={preferences.homePage} replace />
}
