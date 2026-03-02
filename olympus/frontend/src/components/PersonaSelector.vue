<template>
  <div class="persona-selector">
    <button
      v-for="persona in personaStore.personas"
      :key="persona.id"
      class="persona-btn"
      :class="{ active: persona.id === personaStore.activePersonaId }"
      @click="select(persona.id)"
      :title="persona.description"
    >
      <PersonaAvatar :persona="persona" :active="persona.id === personaStore.activePersonaId" />
      <span class="persona-name">{{ persona.name }}</span>
    </button>
  </div>
</template>

<script setup>
import { usePersonaStore } from '../stores/persona'
import { useConversationStore } from '../stores/conversation'
import PersonaAvatar from './PersonaAvatar.vue'

const personaStore = usePersonaStore()
const conversationStore = useConversationStore()

async function select(id) {
  personaStore.setActivePersona(id)
  await conversationStore.fetchConversations(id)
}
</script>

<style scoped>
.persona-selector {
  display: flex;
  gap: 0.75rem;
  justify-content: center;
  flex-wrap: wrap;
}

.persona-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  padding: 0.75rem 1rem;
  border-radius: 12px;
  border: 2px solid var(--border);
  background: var(--bg-surface);
  transition: border-color 0.15s, background 0.15s;
  cursor: pointer;
}

.persona-btn:hover {
  background: var(--bg-hover);
  border-color: var(--text-dim);
}

.persona-btn.active {
  border-color: var(--accent);
  background: var(--bg-hover);
}

.persona-name {
  font-size: 0.8rem;
  color: var(--text-dim);
  font-weight: 500;
}

.persona-btn.active .persona-name {
  color: var(--accent);
}
</style>
