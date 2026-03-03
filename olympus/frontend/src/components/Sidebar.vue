<template>
  <aside class="sidebar" :class="{ open }">
    <!-- Toggle button — always visible even when closed -->
    <button class="toggle-btn" @click="$emit('toggle')" :title="open ? 'Fermer' : 'Ouvrir'">
      {{ open ? '◀' : '▶' }}
    </button>

    <div v-if="open" class="sidebar-inner">

      <!-- Part 1 — Olympus branding -->
      <div class="sidebar-header">
        <img src="/assets/olympus_wo_text.png" alt="Olympus" class="olympus-logo" />
        <span class="olympus-name">Olympus</span>
      </div>

      <!-- Part 2 — Persona selector (3 on one line) -->
      <div class="sidebar-personas">
        <PersonaSelector />
      </div>

      <!-- Part 3 — Conversations -->
      <div class="sidebar-convs">
        <div class="convs-header">
          <span class="convs-label">Conversations</span>
        </div>
        <div class="new-conv-wrap">
          <button class="btn-primary new-conv-btn" @click="newConversation">
            + Nouvelle conversation
          </button>
        </div>
        <ConversationList class="conv-list-scroll" />
      </div>

      <!-- Footer -->
      <div class="sidebar-footer">
        <span class="brand">Olympus v0.2.0</span>
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
/* ── Shell ── */
.sidebar {
  background: var(--bg-surface);
  border-right: 1px solid var(--border);
  transition: width 0.2s;
  display: flex;
  flex-direction: column;
  position: relative;
  flex-shrink: 0;
  width: 0;
}

.sidebar.open {
  width: var(--sidebar-width);
  overflow: hidden;
}

/* ── Toggle button ── */
.toggle-btn {
  position: absolute;
  right: -18px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 10;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  font-size: 0.85rem;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--text-dim);
  box-shadow: 2px 0 6px rgba(0,0,0,0.3);
}

.toggle-btn:hover {
  color: var(--text);
  background: var(--bg-hover);
}

/* ── Inner layout ── */
.sidebar-inner {
  width: var(--sidebar-width);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

/* ── Part 1: Olympus header ── */
.sidebar-header {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 1rem 1rem 0.75rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.olympus-logo {
  width: 32px;
  height: 32px;
  object-fit: contain;
}

.olympus-name {
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--accent);
}

/* ── Part 2: Personas ── */
.sidebar-personas {
  padding: 0.6rem 0.5rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

/* Force personas on one line, compact */
.sidebar-personas :deep(.persona-selector) {
  flex-wrap: nowrap;
  gap: 0.25rem;
}

.sidebar-personas :deep(.persona-btn) {
  flex: 1;
  padding: 0.5rem 0.25rem;
  min-width: 0;
}

.sidebar-personas :deep(.persona-name) {
  font-size: 0.72rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  width: 100%;
  text-align: center;
}

/* ── Part 3: Conversations ── */
.sidebar-convs {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.convs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.75rem 0.4rem;
  flex-shrink: 0;
}

.convs-label {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-dim);
  font-weight: 600;
}

.new-conv-wrap {
  padding: 0.4rem 0.75rem 0.5rem;
  flex-shrink: 0;
}

.new-conv-btn {
  width: 100%;
  font-size: 0.85rem;
}

.conv-list-scroll {
  flex: 1;
  min-height: 0;
}

.sidebar-footer {
  padding: 0.5rem 1rem;
  border-top: 1px solid var(--border);
  text-align: center;
  flex-shrink: 0;
}

.brand {
  font-size: 0.7rem;
  color: var(--text-dim);
  letter-spacing: 0.05em;
}
</style>
