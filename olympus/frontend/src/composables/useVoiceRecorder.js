/**
 * useVoiceRecorder — Push-to-talk voice recorder using MediaRecorder (WebM/Opus).
 *
 * Usage:
 *   const { recording, start, stop } = useVoiceRecorder(onAudioBlob)
 *   onAudioBlob(blob) is called when recording stops
 */
import { ref } from 'vue'

export function useVoiceRecorder(onAudioBlob) {
  const recording = ref(false)
  let mediaRecorder = null
  let chunks = []

  async function start() {
    if (recording.value) return
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      chunks = []
      mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' })

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data)
      }

      mediaRecorder.onstop = () => {
        const blob = new Blob(chunks, { type: 'audio/webm' })
        onAudioBlob(blob)
        stream.getTracks().forEach(t => t.stop())
      }

      mediaRecorder.start()
      recording.value = true
    } catch (err) {
      console.error('Microphone access denied', err)
    }
  }

  function stop() {
    if (!recording.value || !mediaRecorder) return
    mediaRecorder.stop()
    recording.value = false
  }

  return { recording, start, stop }
}
