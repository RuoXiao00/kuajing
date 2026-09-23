import { useState } from 'react'
import { usePreferences } from './usePreferences'
import { HOME_PAGES } from './preferences'
import './Settings.css'

function NicknameForm({ nickname, onSave }) {
  const [draft, setDraft] = useState(nickname)
  const [message, setMessage] = useState('')
  const cleaned = draft.trim()
  const valid = cleaned.length > 0 && Array.from(cleaned).length <= 20
  const changed = cleaned !== nickname

  function submit(event) {
    event.preventDefault()
    if (!valid) { setMessage('昵称请填写 1–20 个字符。'); return }
    if (!changed) return
    onSave(cleaned)
  }

  return <form className="st-profile-form" onSubmit={submit}>
    <label htmlFor="settings-nickname">显示昵称</label>
    <div className="st-name-input"><input id="settings-nickname" value={draft} maxLength={40}
      autoComplete="nickname" aria-describedby="nickname-hint" aria-invalid={!valid}
      onChange={event => { setDraft(event.target.value); setMessage('') }} />
      <button className="st-primary" type="submit" disabled={!changed || !valid}>保存昵称</button></div>
    <p id="nickname-hint">1–20 个字符，会显示在左侧导航底部。</p>
    {(!valid || message) && <p className="st-field-error" role="alert">{message || '昵称请填写 1–20 个字符。'}</p>}
  </form>
}

function PreferenceSwitch({ id, checked, onChange, label }) {
  return <button id={id} className="st-switch" type="button" role="switch" aria-label={label}
    aria-checked={checked} onClick={() => onChange(!checked)}><span /></button>
}

export default function Settings() {
  const { preferences, updatePreferences, resetPreferences, storageWarning } = usePreferences()
  const [notice, setNotice] = useState('')
  const [confirmReset, setConfirmReset] = useState(false)
  const [resetVersion, setResetVersion] = useState(0)

  function save(patch, message = '设置已保存') {
    const saved = updatePreferences(patch)
    setNotice(saved ? message : '设置已在当前页面应用，但未能保存到浏览器。')
    setConfirmReset(false)
  }

  function reset() {
    const saved = resetPreferences()
    setResetVersion(version => version + 1)
    setConfirmReset(false)
    setNotice(saved ? '已恢复默认设置' : '已恢复默认设置，但未能保存到浏览器。')
  }

  return <div className="st-page" translate="no">
    <div className="st-content">
      <header className="st-header"><div><span className="st-eyebrow">PREFERENCES</span><h1>设置</h1><p>管理个人资料和浏览偏好，让使用更顺手。</p></div>
        <span className={`st-storage-tag ${storageWarning ? 'is-warning' : ''}`}><i />{storageWarning ? '本地存储不可用' : '保存在当前浏览器'}</span></header>

      {storageWarning && <p className="st-warning" role="alert">{storageWarning}</p>}
      {notice && <p className="st-notice" role="status">{notice}</p>}

      <section className="st-card" aria-labelledby="profile-heading">
        <div className="st-card-heading"><span className="st-section-number">01</span><div><h2 id="profile-heading">个人资料</h2><p>设置一个熟悉的名字。</p></div></div>
        <div className="st-profile"><div className="st-avatar-wrap"><img src={`${import.meta.env.BASE_URL}pt8.jpg`} alt="当前头像" /><span>本地用户</span></div>
          {/* nickname 是已保存值。保存/重置后重建表单，避免旧草稿覆盖新的偏好。 */}
          <NicknameForm key={`${preferences.nickname}:${resetVersion}`} nickname={preferences.nickname}
            onSave={nickname => save({ nickname }, '昵称已保存，左侧导航已同步更新')} /></div>
      </section>

      <section className="st-card" aria-labelledby="browsing-heading">
        <div className="st-card-heading"><span className="st-section-number">02</span><div><h2 id="browsing-heading">浏览偏好</h2><p>下面的选项修改后会自动保存。</p></div></div>
        <div className="st-row"><div><label htmlFor="settings-home">默认首页</label><p>打开网站首页时，优先进入这个页面。</p></div>
          <select id="settings-home" value={preferences.homePage} onChange={event => save({ homePage: event.target.value })}>
            {HOME_PAGES.map(item => <option key={item.path} value={item.path}>{item.label}</option>)}
          </select></div>
        <div className="st-row"><div><label htmlFor="settings-sidebar">展开左侧导航</label><p>在桌面显示完整导航名称；关闭后使用紧凑图标栏。</p></div>
          <PreferenceSwitch id="settings-sidebar" label="展开左侧导航" checked={!preferences.sidebarCollapsed}
            onChange={expanded => save({ sidebarCollapsed: !expanded })} /></div>
        <div className="st-row"><div><label htmlFor="settings-autoload">热门产品自动加载</label><p>滑动接近底部时自动获取下一页。关闭后可点击“继续加载”。</p></div>
          <PreferenceSwitch id="settings-autoload" label="热门产品自动加载" checked={preferences.autoLoadProducts}
            onChange={autoLoadProducts => save({ autoLoadProducts })} /></div>
      </section>

      <section className="st-card st-storage" aria-labelledby="storage-heading">
        <div className="st-card-heading"><span className="st-section-number">03</span><div><h2 id="storage-heading">设置与存储</h2><p>偏好保存在此浏览器，更换设备需要重新设置。</p></div></div>
        <div className="st-row"><div><strong>恢复默认设置</strong><p>恢复默认昵称、首页、导航和自动加载偏好。</p></div>
          <button className="st-secondary" type="button" onClick={() => setConfirmReset(true)}>恢复默认</button></div>
        {confirmReset && <div className="st-confirm" role="group" aria-label="确认恢复默认设置">
          <p>只重置本页偏好，聊天记录与已生成图片会保留。</p>
          <div><button className="st-secondary" type="button" onClick={() => setConfirmReset(false)}>取消</button><button className="st-primary" type="button" onClick={reset}>确认恢复</button></div>
        </div>}
      </section>
      <footer className="st-footer">跨境阁 · 你的跨境选品与创作工作台</footer>
    </div>
  </div>
}
