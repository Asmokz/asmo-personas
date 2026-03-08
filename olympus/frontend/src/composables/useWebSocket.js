/**
 * useWebSocket — WebSocket composable for streaming chat events.
 *
 * Usage:
 *   const { send, close } = useWebSocket(onEvent)
 *   send({ conv_id, persona_id, content, images })
 */
import { useAuthStore } from '../stores/auth'

export function useWebSocket(onEvent) {
  let ws = null

  function send(payload) {
    return new Promise((resolve, reject) => {
      const authStore = useAuthStore()
      const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
      const token = authStore.accessToken ? `?token=${encodeURIComponent(authStore.accessToken)}` : ''
      const url = `${protocol}://${location.host}/api/chat/stream${token}`
      ws = new WebSocket(url)

      ws.onopen = () => {
        ws.send(JSON.stringify(payload))
      }

      ws.onmessage = (evt) => {
        try {
          const event = JSON.parse(evt.data)
          onEvent(event)
          if (event.type === 'done' || event.type === 'error') {
            ws.close()
            resolve(event)
          }
        } catch (err) {
          console.error('WS parse error', err)
        }
      }

      ws.onerror = (err) => {
        console.error('WebSocket error', err)
        reject(err)
      }

      ws.onclose = () => {
        ws = null
      }
    })
  }

  function close() {
    if (ws) {
      ws.close()
      ws = null
    }
  }

  return { send, close }
}
