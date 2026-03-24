import { mountChatWidget } from './chat-widget.js'
import { mountGraphView } from './graph-view.js'

document.addEventListener('DOMContentLoaded', () => {
  mountChatWidget(document.getElementById('chat-widget'))
  mountGraphView(document.getElementById('graph-view'))
})
