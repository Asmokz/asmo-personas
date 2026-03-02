<template>
  <div v-if="open" class="modal-overlay" @click.self="cancel">
    <div class="modal">
      <h3>Correction</h3>
      <p class="hint">Quelle aurait été la bonne réponse ?</p>
      <textarea v-model="correction" rows="5" placeholder="Saisir la correction…" />
      <div class="modal-actions">
        <button class="btn-secondary" @click="cancel">Annuler</button>
        <button class="btn-primary" @click="submit">Envoyer</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({ open: Boolean, entryId: String })
const emit = defineEmits(['close'])

const correction = ref('')

async function submit() {
  if (!props.entryId) return
  await fetch('/api/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entry_id: props.entryId, quality: 'bad', correction: correction.value }),
  })
  correction.value = ''
  emit('close')
}

function cancel() {
  correction.value = ''
  emit('close')
}
</script>

<style scoped>
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.6);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}

.modal {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.5rem;
  width: 90%;
  max-width: 480px;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.modal h3 { color: var(--accent); font-size: 1.1rem; }
.hint { color: var(--text-dim); font-size: 0.85rem; }

textarea {
  background: var(--input-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  padding: 0.75rem;
  font-family: inherit;
  font-size: 0.9rem;
  resize: vertical;
  outline: none;
}

textarea:focus { border-color: var(--accent); }

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
}

.btn-secondary {
  padding: 0.4rem 1rem;
  border-radius: 8px;
  border: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 0.9rem;
}

.btn-secondary:hover { background: var(--bg-hover); }
</style>
