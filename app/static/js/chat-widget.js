export async function mountChatWidget(root) {
  if (!root) return
  root.innerHTML = `
    <div class="space-y-3">
      <div class="text-sm font-medium">AI Assistant</div>
      <textarea class="w-full rounded-lg border p-3" rows="4" placeholder="Ask a question..."></textarea>
      <button class="rounded-lg border px-4 py-2">Send</button>
      <pre class="min-h-20 rounded-lg bg-slate-50 p-3 text-sm"></pre>
    </div>
  `
  const textarea = root.querySelector('textarea')
  const button = root.querySelector('button')
  const output = root.querySelector('pre')
  button.addEventListener('click', async () => {
    const endpoint = root.dataset.endpoint
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: textarea.value })
    })
    const data = await response.json()
    output.textContent = data.reply || 'No reply'
  })
}
