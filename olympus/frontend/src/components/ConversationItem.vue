<template>
  <div
    class="conv-item"
    :class="{ active }"
    @click="$emit('select', conv.id)"
  >
    <span class="conv-title">{{ title }}</span>
    <button class="delete-btn" @click.stop="$emit('delete', conv.id)" title="Supprimer">×</button>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  conv: { type: Object, required: true },
  active: { type: Boolean, default: false },
})
defineEmits(['select', 'delete'])

const title = computed(() =>
  props.conv.title || `Conversation du ${new Date(props.conv.created_at).toLocaleDateString('fr-FR')}`
)
</script>

<style scoped>
.conv-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.12s;
}

.conv-item:hover { background: var(--bg-hover); }
.conv-item.active { background: var(--bg-hover); border-left: 3px solid var(--accent); padding-left: calc(0.75rem - 3px); }

.conv-title {
  flex: 1;
  font-size: 0.85rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--text);
}

.conv-item.active .conv-title { color: var(--accent); }

.delete-btn {
  opacity: 0;
  color: var(--text-dim);
  font-size: 1.1rem;
  line-height: 1;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  flex-shrink: 0;
}

.conv-item:hover .delete-btn { opacity: 1; }
.delete-btn:hover { background: var(--border); color: var(--text); }
</style>
