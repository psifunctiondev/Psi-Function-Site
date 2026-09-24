import { mountChatWidget } from './chat-widget.js'
import { mountGraphView } from './graph-view.js'
import './portal-kanban.js'
import './portal-backlog.js'
import './portal-progress.js'

document.addEventListener('DOMContentLoaded', () => {
  mountChatWidget(document.getElementById('chat-widget'))
  mountGraphView(document.getElementById('graph-view'))
})
