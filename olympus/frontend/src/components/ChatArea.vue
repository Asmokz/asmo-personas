<template>
  <div class="chat-area">
    <!-- Header -->
    <div class="chat-header">
      <PersonaAvatar v-if="activePersona" :persona="activePersona" :active="true" />
      <div class="header-info">
        <span class="conv-title">{{ convTitle }}</span>
        <span class="persona-name" v-if="activePersona">{{ activePersona.name }}</span>
      </div>
    </div>

    <!-- Messages -->
    <div class="messages-container" ref="messagesEl">
      <MessageBubble
        v-for="msg in displayMessages"
        :key="msg.id"
        :msg="msg"
        @open-correction="openCorrection"
      />
      <TypingIndicator :status="chatStore.typingStatus" />
    </div>

    <!-- Input -->
    <InputBar />

    <!-- Feedback modal -->
    <FeedbackModal
      :open="feedbackOpen"
      :entry-id="feedbackEntryId"
      @close="feedbackOpen = false"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { usePersonaStore } from '../stores/persona'
import { useConversationStore } from '../stores/conversation'
import { useChatStore } from '../stores/chat'
import PersonaAvatar from './PersonaAvatar.vue'
import MessageBubble from './MessageBubble.vue'
import TypingIndicator from './TypingIndicator.vue'
import InputBar from './InputBar.vue'
import FeedbackModal from './FeedbackModal.vue'

const personaStore = usePersonaStore()
const conversationStore = useConversationStore()
const chatStore = useChatStore()
const messagesEl = ref(null)
const feedbackOpen = ref(false)
const feedbackEntryId = ref(null)

const activePersona = computed(() => personaStore.getActive())

const convTitle = computed(() => {
  const id = conversationStore.activeConvId
  const conv = conversationStore.conversations.find(c => c.id === id)
  return conv?.title || 'Nouvelle conversation'
})

const displayMessages = computed(() =>
  chatStore.messages.filter(m => m.role === 'user' || m.role === 'assistant')
)

function openCorrection(entryId) {
  feedbackEntryId.value = entryId
  feedbackOpen.value = true
}

// Scroll to bottom on new messages
watch(
  () => chatStore.messages.length,
  async () => {
    await nextTick()
    if (messagesEl.value) {
      messagesEl.value.scrollTop = messagesEl.value.scrollHeight
    }
  }
)
</script>

<style scoped>
.chat-area {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
  background: var(--bg-surface);
}

.header-info {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.conv-title {
  font-size: 0.95rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 400px;
}

.persona-name {
  font-size: 0.78rem;
  color: var(--accent);
}

.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 1rem 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
</style>
