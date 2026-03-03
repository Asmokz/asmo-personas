<template>
  <div class="input-bar">
    <!-- Image previews -->
    <div v-if="chatStore.pendingImages.length" class="image-previews">
      <div v-for="(img, i) in chatStore.pendingImages" :key="i" class="image-preview">
        <img :src="`data:image/jpeg;base64,${img}`" alt="Image jointe" />
        <button @click="removeImage(i)" class="remove-img">×</button>
      </div>
    </div>

    <div class="input-row">
      <!-- Image upload -->
      <button class="icon-btn" @click="pickImage" title="Joindre une image">📎</button>

      <!-- Mic (push-to-talk) -->
      <button
        class="icon-btn"
        :class="{ recording: voiceRecorder.recording.value }"
        @mousedown="voiceRecorder.start"
        @mouseup="voiceRecorder.stop"
        @touchstart.prevent="voiceRecorder.start"
        @touchend.prevent="voiceRecorder.stop"
        title="Maintenir pour dicter"
      >🎤</button>

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
      >➤</button>
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

const chatStore = useChatStore()
const personaStore = usePersonaStore()
const conversationStore = useConversationStore()
const inputRef = ref(null)
const inputText = ref('')

const placeholder = computed(() =>
  chatStore.streaming ? 'En cours…' : 'Écris un message…'
)

function autoResize() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

// Voice recorder
const voiceRecorder = useVoiceRecorder(async (blob) => {
  chatStore.typingStatus.value = 'Transcription…'
  try {
    const fd = new FormData()
    fd.append('audio', blob, 'recording.webm')
    const res = await fetch('/api/voice', { method: 'POST', body: fd })
    const data = await res.json()
    if (data.text) {
      inputText.value = data.text
      autoResize()
    }
  } catch (err) {
    console.error('STT failed', err)
  } finally {
    chatStore.typingStatus.value = ''
  }
})

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
    // Refresh conversation list to pick up the LLM-generated title
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

  // Add user message to UI
  chatStore.addMessage({ id: Date.now(), role: 'user', content: text, entry_id: null })
  inputText.value = ''
  if (inputRef.value) inputRef.value.style.height = 'auto'

  const images = [...chatStore.pendingImages]
  chatStore.clearPendingImages()

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
  font-size: 1.1rem;
  padding: 0.4rem;
  border-radius: 8px;
  transition: background 0.12s;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.icon-btn:hover { background: var(--bg-hover); }
.icon-btn:disabled { opacity: 0.4; cursor: default; }
.icon-btn.recording { background: var(--accent); animation: pulse 1s infinite; }
.send-btn { color: var(--accent); }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}
</style>
