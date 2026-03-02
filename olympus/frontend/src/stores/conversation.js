import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useConversationStore = defineStore('conversation', () => {
  const conversations = ref([])
  const activeConvId = ref(null)
  const loading = ref(false)

  async function fetchConversations(personaId) {
    try {
      const res = await fetch(`/api/conversations?persona_id=${personaId}`)
      conversations.value = await res.json()
    } catch (err) {
      console.error('fetchConversations failed', err)
    }
  }

  async function createConversation(personaId) {
    const res = await fetch('/api/conversations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ persona_id: personaId }),
    })
    if (!res.ok) throw new Error('Failed to create conversation')
    const conv = await res.json()
    conversations.value.unshift(conv)
    activeConvId.value = conv.id
    return conv
  }

  async function deleteConversation(convId) {
    await fetch(`/api/conversations/${convId}`, { method: 'DELETE' })
    conversations.value = conversations.value.filter(c => c.id !== convId)
    if (activeConvId.value === convId) {
      activeConvId.value = conversations.value[0]?.id || null
    }
  }

  async function loadHistory(convId) {
    const res = await fetch(`/api/conversations/${convId}`)
    return await res.json()
  }

  function setActive(convId) {
    activeConvId.value = convId
  }

  return {
    conversations,
    activeConvId,
    loading,
    fetchConversations,
    createConversation,
    deleteConversation,
    loadHistory,
    setActive,
  }
})
