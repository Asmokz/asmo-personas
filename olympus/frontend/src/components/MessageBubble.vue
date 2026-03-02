<template>
  <div class="msg-wrapper" :class="msg.role">
    <div class="bubble">
      <div class="content" v-html="rendered" />
      <FeedbackButtons
        v-if="msg.role === 'assistant'"
        :entry-id="msg.entry_id"
        @open-correction="$emit('open-correction', $event)"
      />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import FeedbackButtons from './FeedbackButtons.vue'

const props = defineProps({
  msg: { type: Object, required: true },
})
defineEmits(['open-correction'])

// Very minimal markdown-like rendering (bold, code, newlines)
const rendered = computed(() => {
  let text = props.msg.content || ''
  // Escape HTML
  text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  // Code blocks
  text = text.replace(/```[\s\S]*?```/g, m => `<pre><code>${m.slice(3, -3).replace(/^[a-z]*\n/, '')}</code></pre>`)
  // Inline code
  text = text.replace(/`([^`]+)`/g, '<code>$1</code>')
  // Bold
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  // Newlines
  text = text.replace(/\n/g, '<br />')
  return text
})
</script>

<style scoped>
.msg-wrapper {
  display: flex;
  padding: 0.25rem 1rem;
}

.msg-wrapper.user { justify-content: flex-end; }
.msg-wrapper.assistant { justify-content: flex-start; }

.bubble {
  max-width: 75%;
  padding: 0.65rem 0.9rem;
  border-radius: 14px;
  font-size: 0.92rem;
  line-height: 1.55;
}

.user .bubble {
  background: var(--bubble-user);
  color: var(--text);
  border-bottom-right-radius: 4px;
}

.assistant .bubble {
  background: var(--bubble-persona);
  color: var(--text);
  border-bottom-left-radius: 4px;
  border: 1px solid var(--border);
}

.content :deep(code) {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.85em;
  background: var(--bg);
  padding: 1px 4px;
  border-radius: 4px;
}

.content :deep(pre) {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.75rem;
  overflow-x: auto;
  margin: 0.5rem 0;
}

.content :deep(pre code) {
  background: none;
  padding: 0;
}

.content :deep(strong) { color: var(--accent2); }
</style>
