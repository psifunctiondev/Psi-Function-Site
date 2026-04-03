/**
 * chat-widget.js — Prospect chat widget for the Psi Function home page.
 *
 * Renders an expandable chat interface that connects to the /api/chat
 * endpoint. Maintains conversation history for context-aware replies.
 */

export async function mountChatWidget(root) {
  if (!root) return

  const endpoint = root.dataset.endpoint || '/api/chat'
  const history = [] // { role, content } pairs

  // Build DOM
  root.innerHTML = `
    <div class="chat-widget">
      <button class="chat-widget__toggle" aria-label="Open chat" aria-expanded="false">
        <svg class="chat-widget__icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>

      <div class="chat-widget__panel" hidden>
        <div class="chat-widget__header">
          <span class="chat-widget__title">Chat with Psi Function</span>
          <button class="chat-widget__close" aria-label="Close chat">&times;</button>
        </div>
        <div class="chat-widget__messages" aria-live="polite">
          <div class="chat-widget__message chat-widget__message--assistant">
            Hi! I'm here to help you explore how technology could work for your
            business. What's on your mind?
          </div>
        </div>
        <form class="chat-widget__form">
          <input
            type="text"
            class="chat-widget__input"
            placeholder="Ask about your business..."
            maxlength="2000"
            autocomplete="off"
          >
          <button type="submit" class="chat-widget__send" aria-label="Send message">
            <svg viewBox="0 0 24 24" fill="none" width="18" height="18" aria-hidden="true">
              <path d="M22 2L11 13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
              <path d="M22 2L15 22L11 13L2 9L22 2Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </button>
        </form>
      </div>
    </div>
  `

  const toggle = root.querySelector('.chat-widget__toggle')
  const panel = root.querySelector('.chat-widget__panel')
  const closeBtn = root.querySelector('.chat-widget__close')
  const messages = root.querySelector('.chat-widget__messages')
  const form = root.querySelector('.chat-widget__form')
  const input = root.querySelector('.chat-widget__input')

  function openChat() {
    panel.hidden = false
    toggle.setAttribute('aria-expanded', 'true')
    toggle.hidden = true
    input.focus()
  }

  function closeChat() {
    panel.hidden = true
    toggle.setAttribute('aria-expanded', 'false')
    toggle.hidden = false
  }

  toggle.addEventListener('click', openChat)
  closeBtn.addEventListener('click', closeChat)

  function addMessage(role, text) {
    const div = document.createElement('div')
    div.className = `chat-widget__message chat-widget__message--${role}`
    div.textContent = text
    messages.appendChild(div)
    messages.scrollTop = messages.scrollHeight
  }

  function setLoading(on) {
    const existing = messages.querySelector('.chat-widget__typing')
    if (on && !existing) {
      const dot = document.createElement('div')
      dot.className = 'chat-widget__message chat-widget__message--assistant chat-widget__typing'
      dot.textContent = '...'
      messages.appendChild(dot)
      messages.scrollTop = messages.scrollHeight
    } else if (!on && existing) {
      existing.remove()
    }
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault()
    const text = input.value.trim()
    if (!text) return

    addMessage('user', text)
    history.push({ role: 'user', content: text })
    input.value = ''
    setLoading(true)

    try {
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: text, history }),
      })
      const data = await resp.json()
      const reply = data.reply || 'Sorry, something went wrong.'
      setLoading(false)
      addMessage('assistant', reply)
      history.push({ role: 'assistant', content: reply })
    } catch (err) {
      setLoading(false)
      addMessage(
        'assistant',
        "I'm having trouble connecting. Please try again or email info@psifunction.com."
      )
    }
  })
}
