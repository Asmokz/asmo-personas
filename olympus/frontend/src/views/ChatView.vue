<template>
  <div class="app" :class="{ 'light-mode': !isDark }"
       @touchstart.passive="onTouchStart"
       @touchend.passive="onTouchEnd">
    <Sidebar :open="sidebarOpen" :drag-transform="sidebarDragTransform" @toggle="sidebarOpen = !sidebarOpen" />
    <main class="main-content">
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import Sidebar from '../components/Sidebar.vue'
import ChatArea from '../components/ChatArea.vue'
import PersonaSelector from '../components/PersonaSelector.vue'
import { usePersonaStore } from '../stores/persona'
import { useConversationStore } from '../stores/conversation'

const SIDEBAR_W = 280

const isDark = ref(true)
const sidebarOpen = ref(true)
const personaStore = usePersonaStore()
const conversationStore = useConversationStore()

const touchStartX = ref(0)
const touchStartY = ref(0)
const dragDx = ref(null)

const sidebarDragTransform = computed(() => {
  if (dragDx.value === null) return null
  if (sidebarOpen.value) {
    return Math.max(-SIDEBAR_W, Math.min(0, dragDx.value))
  } else {
    return Math.max(-SIDEBAR_W, Math.min(0, -SIDEBAR_W + dragDx.value))
  }
})

function onTouchStart(e) {
  touchStartX.value = e.touches[0].clientX
  touchStartY.value = e.touches[0].clientY
  dragDx.value = null
}

function handleTouchMove(e) {
  const dx = e.touches[0].clientX - touchStartX.value
  const dy = e.touches[0].clientY - touchStartY.value

  if (dragDx.value === null) {
    if (Math.abs(dy) > Math.abs(dx) + 5) return
    if (!sidebarOpen.value && (dx < 0 || touchStartX.value > 40)) return
    if (sidebarOpen.value && dx > 0) return
  }

  dragDx.value = dx
  e.preventDefault()
}

function onTouchEnd(e) {
  if (dragDx.value === null) return
  const dx = e.changedTouches[0].clientX - touchStartX.value

  if (sidebarOpen.value) {
    sidebarOpen.value = dx > -(SIDEBAR_W / 3)
  } else {
    sidebarOpen.value = dx > SIDEBAR_W / 3
  }
  dragDx.value = null
}

let _touchMoveHandler = null

onMounted(async () => {
  if (window.innerWidth < 768) sidebarOpen.value = false
  _touchMoveHandler = handleTouchMove
  window.addEventListener('touchmove', _touchMoveHandler, { passive: false })
  await personaStore.fetchPersonas()
})

onUnmounted(() => {
  if (_touchMoveHandler) window.removeEventListener('touchmove', _touchMoveHandler)
})
</script>
