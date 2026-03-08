/**
 * useVoiceRecorder — Push-to-talk voice recorder using MediaRecorder.
 *
 * Automatically selects the best supported MIME type (WebM/Opus, then fallbacks).
 * Calls onAudioBlob(blob) when recording stops, onError(message) on failure.
 */
import { ref } from 'vue'

const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/ogg',
  'audio/mp4',
]

function getSupportedMimeType() {
  if (typeof MediaRecorder === 'undefined') return null
  return MIME_CANDIDATES.find(t => MediaRecorder.isTypeSupported(t)) ?? ''
}

export function useVoiceRecorder(onAudioBlob, onError) {
  const recording = ref(false)
  let mediaRecorder = null
  let chunks = []

  async function start() {
    if (recording.value) return

    if (!navigator.mediaDevices?.getUserMedia) {
      onError?.('Microphone non supporté par ce navigateur.')
      return
    }

    const mimeType = getSupportedMimeType()
    if (mimeType === null) {
      onError?.('Enregistrement audio non supporté par ce navigateur.')
      return
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      chunks = []

      const options = mimeType ? { mimeType } : {}
      mediaRecorder = new MediaRecorder(stream, options)

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data)
      }

      mediaRecorder.onstop = () => {
        const type = mimeType || 'audio/webm'
        const blob = new Blob(chunks, { type })
        onAudioBlob(blob)
        stream.getTracks().forEach(t => t.stop())
      }

      mediaRecorder.onerror = (e) => {
        recording.value = false
        stream.getTracks().forEach(t => t.stop())
        onError?.(`Erreur d'enregistrement : ${e.error?.message ?? 'inconnue'}`)
      }

      mediaRecorder.start()
      recording.value = true
    } catch (err) {
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        onError?.('Permission microphone refusée. Autorise l\'accès dans les paramètres du navigateur.')
      } else if (err.name === 'NotFoundError') {
        onError?.('Aucun microphone détecté.')
      } else {
        onError?.(`Microphone inaccessible : ${err.message}`)
      }
    }
  }

  function stop() {
    if (!recording.value || !mediaRecorder) return
    mediaRecorder.stop()
    recording.value = false
  }

  return { recording, start, stop }
}
