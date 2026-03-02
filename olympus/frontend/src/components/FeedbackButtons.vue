<template>
  <div class="feedback-btns" v-if="entryId">
    <button
      class="fb-btn"
      :class="{ active: voted === 'good' }"
      @click="vote('good')"
      title="Bonne réponse"
    >👍</button>
    <button
      class="fb-btn"
      :class="{ active: voted === 'bad' }"
      @click="openCorrection"
      title="Mauvaise réponse"
    >👎</button>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  entryId: { type: String, default: null },
})
const emit = defineEmits(['open-correction'])

const voted = ref(null)

async function vote(quality) {
  if (!props.entryId || voted.value) return
  voted.value = quality
  await fetch('/api/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entry_id: props.entryId, quality }),
  })
}

function openCorrection() {
  if (!props.entryId || voted.value) return
  emit('open-correction', props.entryId)
}
</script>

<style scoped>
.feedback-btns {
  display: flex;
  gap: 0.25rem;
  margin-top: 0.25rem;
}

.fb-btn {
  font-size: 0.85rem;
  padding: 2px 6px;
  border-radius: 6px;
  background: transparent;
  opacity: 0.4;
  transition: opacity 0.15s, background 0.15s;
}

.fb-btn:hover { opacity: 1; background: var(--bg-hover); }
.fb-btn.active { opacity: 1; background: var(--bg-hover); }
</style>
