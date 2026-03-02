<template>
  <aside class="sidebar" :class="{ open }">
    <!-- Toggle -->
    <button class="toggle-btn" @click="$emit('toggle')" :title="open ? 'Fermer' : 'Ouvrir'">
      {{ open ? '◀' : '▶' }}
    </button>

    <div v-if="open" class="sidebar-inner">
      <!-- Persona selector -->
      <div class="section">
        <PersonaSelector />
      </div>

      <!-- New conversation -->
      <div class="section">
        <button class="btn-primary new-conv-btn" @click="newConversation">
          + Nouvelle conversation
        </button>
      </div>

      <!-- Conversation list -->
      <ConversationList class="flex-grow" />

      <!-- Asmo avatar / branding -->
      <div class="sidebar-footer">
        <span class="brand">Olympus v0.2</span>
      </div>
    </div>
  </aside>
</template>

<script setup>
import PersonaSelector from './PersonaSelector.vue'
import ConversationList from './ConversationList.vue'
import { usePersonaStore } from '../stores/persona'
import { useConversationStore } from '../stores/conversation'
import { useChatStore } from '../stores/chat'

defineProps({ open: Boolean })
defineEmits(['toggle'])

const personaStore = usePersonaStore()
const conversationStore = useConversationStore()
const chatStore = useChatStore()

async function newConversation() {
  chatStore.clear()
  await conversationStore.createConversation(personaStore.activePersonaId)
  await conversationStore.fetchConversations(personaStore.activePersonaId)
}
</script>

<style scoped>
.sidebar {
  width: 0;
  overflow: hidden;
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  transition: width 0.2s;
  display: flex;
  flex-direction: column;
  position: relative;
  flex-shrink: 0;
}

.sidebar.open {
  width: var(--sidebar-width);
}

.sidebar-inner {
  width: var(--sidebar-width);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  padding: 0.75rem 0;
}

.toggle-btn {
  position: absolute;
  right: -14px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 10;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  font-size: 0.7rem;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--text-dim);
}

.toggle-btn:hover { color: var(--text); background: var(--bg-hover); }

.section {
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border);
}

.new-conv-btn {
  width: 100%;
  font-size: 0.85rem;
}

.flex-grow { flex: 1; min-height: 0; }

.sidebar-footer {
  padding: 0.5rem 1rem;
  border-top: 1px solid var(--border);
  text-align: center;
}

.brand {
  font-size: 0.7rem;
  color: var(--text-dim);
  letter-spacing: 0.05em;
}
</style>
