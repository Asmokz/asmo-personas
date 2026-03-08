<template>
  <div class="input-bar">
    <!-- Image previews -->
    <div v-if="chatStore.pendingImages.length" class="image-previews">
      <div v-for="(img, i) in chatStore.pendingImages" :key="i" class="image-preview">
        <img :src="`data:image/jpeg;base64,${img}`" alt="Image jointe" />
        <button @click="removeImage(i)" class="remove-img">×</button>
      </div>
    </div>

    <!-- Mic error toast -->
    <div v-if="micError" class="mic-error">{{ micError }}</div>

    <div class="input-row">
      <!-- Image upload -->
      <button class="icon-btn" @click="pickImage" title="Joindre une image">
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect width="18" height="18" x="3" y="3" rx="2" ry="2"/>
          <circle cx="9" cy="9" r="2"/>
          <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>
        </svg>
      </button>

      <!-- Mic (push-to-talk) -->
      <button
        class="icon-btn"
        :class="{ recording: voiceRecorder.recording.value }"
        @mousedown="voiceRecorder.start"
        @mouseup="voiceRecorder.stop"
        @touchstart.prevent="voiceRecorder.start"
        @touchend.prevent="voiceRecorder.stop"
        title="Maintenir pour dicter"
      >
        <svg v-if="!voiceRecorder.recording.value" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
          <line x1="12" x2="12" y1="19" y2="22"/>
        </svg>
        <svg v-else xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>
          <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
          <line x1="12" x2="12" y1="19" y2="22"/>
        </svg>
      </button>

      <!-- Text input -->
      <textarea
        ref="inputRef"
        v-model="inputText"
        class="text-input"
        :placeholder="placeholder"
        rows="1"
        @keydown.enter.exact.prevent="send"
        @input="autoResize"
        :disabled="chatStore.streaming"
      />

      <!-- Send -->
      <button
        class="icon-btn send-btn"
        @click="send"
        :disabled="(!inputText.trim() && !chatStore.pendingImages.length) || chatStore.streaming"
        title="Envoyer (Entrée)"
      >
        <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="m22 2-7 20-4-9-9-4Z"/>
          <path d="M22 2 11 13"/>
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useChatStore } from '../stores/chat'
import { usePersonaStore } from '../stores/persona'
import { useConversationStore } from '../stores/conversation'
import { useVoiceRecorder } from '../composables/useVoiceRecorder'
import { useImageUpload } from '../composables/useImageUpload'
import { useWebSocket } from '../composables/useWebSocket'
import { useApi } from '../composables/useApi'

const chatStore = useChatStore()
const personaStore = usePersonaStore()
const conversationStore = useConversationStore()
const inputRef = ref(null)
const inputText = ref('')
const micError = ref('')
let micErrorTimer = null

const placeholder = computed(() =>
  chatStore.streaming ? 'En cours…' : 'Écris un message…'
)

function autoResize() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function showMicError(msg) {
  micError.value = msg
  clearTimeout(micErrorTimer)
  micErrorTimer = setTimeout(() => { micError.value = '' }, 5000)
}

// Voice recorder
const voiceRecorder = useVoiceRecorder(
  async (blob) => {
    chatStore.typingStatus.value = 'Transcription…'
    try {
      const fd = new FormData()
      fd.append('audio', blob, 'recording.webm')
      const { apiFetch } = useApi()
      // Don't set Content-Type — let browser set multipart boundary
      const res = await apiFetch('/api/voice', { method: 'POST', body: fd, _noContentType: true })
      const data = await res.json()
      if (data.text) {
        inputText.value = data.text
        autoResize()
      }
    } catch (err) {
      showMicError('Transcription échouée. Réessaie.')
    } finally {
      chatStore.typingStatus.value = ''
    }
  },
  (errMsg) => showMicError(errMsg),
)

// Image upload
const { pickImage } = useImageUpload((b64) => {
  chatStore.addPendingImage(b64)
})

function removeImage(i) {
  chatStore.pendingImages.splice(i, 1)
}

// WebSocket send
const { send: wsSend } = useWebSocket((event) => {
  const { type } = event
  if (type === 'token') chatStore.onToken(event.content)
  else if (type === 'tool_start') chatStore.onToolStart(event.name)
  else if (type === 'done') {
    chatStore.endStream(event.entry_id)
    conversationStore.fetchConversations(personaStore.activePersonaId)
  }
  else if (type === 'error') {
    chatStore.endStream('')
    console.error('LLM error:', event.message)
  }
})

async function send() {
  const text = inputText.value.trim()
  if ((!text && !chatStore.pendingImages.length) || chatStore.streaming) return

  const convId = conversationStore.activeConvId
  if (!convId) return

  const images = [...chatStore.pendingImages]
  chatStore.clearPendingImages()

  chatStore.addMessage({ id: Date.now(), role: 'user', content: text, entry_id: null, images: images.length ? images : undefined })
  inputText.value = ''
  if (inputRef.value) inputRef.value.style.height = 'auto'

  chatStore.startStream()

  try {
    await wsSend({
      conv_id: convId,
      persona_id: personaStore.activePersonaId,
      content: text,
      images: images.length ? images : undefined,
    })
  } catch (err) {
    chatStore.endStream('')
    console.error('Send failed', err)
  }
}
</script>

<style scoped>
.input-bar {
  padding: 0.75rem 1rem;
  border-top: 1px solid var(--border);
  background: var(--bg-surface);
}

.image-previews {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-bottom: 0.5rem;
}

.image-preview {
  position: relative;
  width: 60px;
  height: 60px;
}

.image-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--border);
}

.remove-img {
  position: absolute;
  top: -6px; right: -6px;
  width: 18px; height: 18px;
  border-radius: 50%;
  background: var(--accent);
  color: #fff;
  font-size: 0.8rem;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer;
}

.mic-error {
  font-size: 0.78rem;
  color: var(--accent);
  margin-bottom: 0.4rem;
  padding: 0.25rem 0.5rem;
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border-radius: 6px;
  border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
}

.input-row {
  display: flex;
  align-items: flex-end;
  gap: 0.5rem;
}

.text-input {
  flex: 1;
  background: var(--input-bg);
  border: 1px solid var(--border);
  border-radius: 12px;
  color: var(--text);
  font-family: inherit;
  font-size: 0.95rem;
  padding: 0.6rem 0.9rem;
  resize: none;
  outline: none;
  max-height: 160px;
  overflow-y: auto;
  line-height: 1.4;
}

.text-input:focus { border-color: var(--accent); }
.text-input:disabled { opacity: 0.6; }

.icon-btn {
  padding: 0.4rem;
  border-radius: 8px;
  transition: background 0.12s, color 0.12s;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--accent);
}

.icon-btn:hover { background: var(--bg-hover); }
.icon-btn:disabled { opacity: 0.4; cursor: default; }
.icon-btn.recording { background: var(--accent); color: #fff; animation: pulse 1s infinite; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}
</style>
