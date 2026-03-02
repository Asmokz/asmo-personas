import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useChatStore = defineStore('chat', () => {
  const messages = ref([])
  const streaming = ref(false)
  const typingStatus = ref('')  // '' | 'Transcription…' | 'Réflexion…' | 'Recherche…'
  const pendingImages = ref([]) // base64 strings

  function addMessage(msg) {
    messages.value.push(msg)
  }

  function appendToLast(content) {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      last.content += content
    }
  }

  function setMessages(msgs) {
    messages.value = msgs.map(m => ({
      id: m.id || Date.now() + Math.random(),
      role: m.role,
      content: m.content,
      entry_id: m.entry_id || null,
    }))
  }

  function startStream() {
    streaming.value = true
    typingStatus.value = 'Réflexion…'
    messages.value.push({ id: Date.now(), role: 'assistant', content: '', entry_id: null })
  }

  function onToolStart(name) {
    typingStatus.value = `Recherche… (${name})`
  }

  function onToken(content) {
    typingStatus.value = ''
    appendToLast(content)
  }

  function endStream(entryId) {
    streaming.value = false
    typingStatus.value = ''
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      last.entry_id = entryId
    }
  }

  function clear() {
    messages.value = []
    streaming.value = false
    typingStatus.value = ''
    pendingImages.value = []
  }

  function addPendingImage(base64) {
    pendingImages.value.push(base64)
  }

  function clearPendingImages() {
    pendingImages.value = []
  }

  return {
    messages,
    streaming,
    typingStatus,
    pendingImages,
    addMessage,
    appendToLast,
    setMessages,
    startStream,
    onToolStart,
    onToken,
    endStream,
    clear,
    addPendingImage,
    clearPendingImages,
  }
})
