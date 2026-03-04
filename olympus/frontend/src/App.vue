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
import Sidebar from './components/Sidebar.vue'
import ChatArea from './components/ChatArea.vue'
import PersonaSelector from './components/PersonaSelector.vue'
import { usePersonaStore } from './stores/persona'
import { useConversationStore } from './stores/conversation'

const SIDEBAR_W = 280  // matches --sidebar-width

const isDark = ref(true)
const sidebarOpen = ref(true)
const personaStore = usePersonaStore()
const conversationStore = useConversationStore()

// ── Touch gesture state ──────────────────────────────────────────────────
const touchStartX = ref(0)
const touchStartY = ref(0)
const dragDx = ref(null)   // null = not dragging, number = current horizontal delta

// Transform to apply to sidebar during drag (null = use CSS classes)
const sidebarDragTransform = computed(() => {
  if (dragDx.value === null) return null
  if (sidebarOpen.value) {
    // Dragging to close: 0 → -SIDEBAR_W
    return Math.max(-SIDEBAR_W, Math.min(0, dragDx.value))
  } else {
    // Dragging to open: -SIDEBAR_W → 0
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

  // Decide whether to start tracking on first significant move
  if (dragDx.value === null) {
    // Ignore vertical scrolls
    if (Math.abs(dy) > Math.abs(dx) + 5) return
    // Closed sidebar: only track right swipe from left edge (≤ 40px)
    if (!sidebarOpen.value && (dx < 0 || touchStartX.value > 40)) return
    // Open sidebar: only track left swipe
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
  // Start closed on mobile
  if (window.innerWidth < 768) sidebarOpen.value = false

  // passive:false required to call preventDefault() and block scroll during horizontal drag
  _touchMoveHandler = handleTouchMove
  window.addEventListener('touchmove', _touchMoveHandler, { passive: false })

  await personaStore.fetchPersonas()
})

onUnmounted(() => {
  if (_touchMoveHandler) window.removeEventListener('touchmove', _touchMoveHandler)
})
</script>

<style>
@import './assets/styles.css';
</style>
