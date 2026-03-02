<template>
  <div class="app" :class="{ 'light-mode': !isDark }">
    <Sidebar :open="sidebarOpen" @toggle="sidebarOpen = !sidebarOpen" />
    <main class="main-content" :class="{ 'sidebar-open': sidebarOpen }">
      <ChatArea v-if="conversationStore.activeConvId" />
      <div v-else class="welcome">
        <div class="welcome-inner">
          <h1>Olympus</h1>
          <p>Sélectionne une conversation ou crée-en une nouvelle.</p>
          <PersonaSelector />
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import Sidebar from './components/Sidebar.vue'
import ChatArea from './components/ChatArea.vue'
import PersonaSelector from './components/PersonaSelector.vue'
import { usePersonaStore } from './stores/persona'
import { useConversationStore } from './stores/conversation'

const isDark = ref(true)
const sidebarOpen = ref(true)
const personaStore = usePersonaStore()
const conversationStore = useConversationStore()

onMounted(async () => {
  await personaStore.fetchPersonas()
})
</script>

<style>
@import './assets/styles.css';
</style>
