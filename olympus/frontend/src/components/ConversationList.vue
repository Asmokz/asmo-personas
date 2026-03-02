<template>
  <div class="conv-list">
    <div v-if="conversations.length === 0" class="empty">
      Aucune conversation
    </div>
    <ConversationItem
      v-for="conv in conversations"
      :key="conv.id"
      :conv="conv"
      :active="conv.id === conversationStore.activeConvId"
      @select="handleSelect"
      @delete="handleDelete"
    />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useConversationStore } from '../stores/conversation'
import { usePersonaStore } from '../stores/persona'
import { useChatStore } from '../stores/chat'
import ConversationItem from './ConversationItem.vue'

const conversationStore = useConversationStore()
const personaStore = usePersonaStore()
const chatStore = useChatStore()

const conversations = computed(() =>
  conversationStore.conversations.filter(c => c.persona_id === personaStore.activePersonaId)
)

async function handleSelect(convId) {
  chatStore.clear()
  conversationStore.setActive(convId)
  const data = await conversationStore.loadHistory(convId)
  const msgs = (data.history || [])
    .filter(m => m.role === 'user' || m.role === 'assistant')
    .map((m, i) => ({ id: i, role: m.role, content: m.content, entry_id: null }))
  chatStore.setMessages(msgs)
}

async function handleDelete(convId) {
  if (!confirm('Supprimer cette conversation ?')) return
  await conversationStore.deleteConversation(convId)
  chatStore.clear()
}
</script>

<style scoped>
.conv-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
  flex: 1;
  padding: 0 0.25rem;
}

.empty {
  text-align: center;
  color: var(--text-dim);
  font-size: 0.8rem;
  padding: 1rem 0;
}
</style>
