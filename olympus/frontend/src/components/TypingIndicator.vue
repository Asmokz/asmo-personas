<template>
  <div v-if="status" class="typing-indicator">
    <span class="dots"><span /><span /><span /></span>
    <span class="status-text">{{ status }}</span>
  </div>
</template>

<script setup>
defineProps({ status: { type: String, default: '' } })
</script>

<style scoped>
.typing-indicator {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0;
  color: var(--text-dim);
  font-size: 0.85rem;
}

.dots {
  display: flex;
  gap: 3px;
  align-items: center;
}

.dots span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: bounce 1.2s infinite ease-in-out;
}

.dots span:nth-child(2) { animation-delay: 0.2s; }
.dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: translateY(0); opacity: 0.5; }
  40% { transform: translateY(-5px); opacity: 1; }
}

.status-text { font-style: italic; }
</style>
