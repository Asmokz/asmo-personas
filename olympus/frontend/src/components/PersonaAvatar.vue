<template>
  <div class="persona-avatar" :class="{ active }" :title="persona.name">
    <img
      :src="persona.avatar_url"
      :alt="persona.name"
      @error="onImgError"
      class="avatar-img"
    />
    <span v-if="showInitial" class="avatar-initial" :style="{ background: persona.color }">
      {{ persona.name[0] }}
    </span>
    <span v-if="active" class="active-dot" />
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  persona: { type: Object, required: true },
  active: { type: Boolean, default: false },
})

const showInitial = ref(false)
function onImgError() { showInitial.value = true }
</script>

<style scoped>
.persona-avatar {
  position: relative;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  overflow: visible;
  flex-shrink: 0;
}

.avatar-img {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  object-fit: cover;
  border: 2px solid var(--border);
}

.persona-avatar.active .avatar-img {
  border-color: var(--accent);
}

.avatar-initial {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.1rem;
  font-weight: bold;
  color: #fff;
}

.active-dot {
  position: absolute;
  bottom: 1px;
  right: 1px;
  width: 10px;
  height: 10px;
  background: #4caf50;
  border-radius: 50%;
  border: 2px solid var(--bg);
}
</style>
