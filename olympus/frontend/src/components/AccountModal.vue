<template>
  <Teleport to="body">
    <div class="modal-overlay" @click.self="$emit('close')">
      <div class="modal">
        <div class="modal-header">
          <h2>Gestion du compte</h2>
          <button class="close-btn" @click="$emit('close')">✕</button>
        </div>

        <div class="modal-body">
          <div class="user-info">
            <span class="user-icon">👤</span>
            <div>
              <div class="user-name">{{ authStore.user?.username }}</div>
              <div class="user-email">{{ authStore.user?.email }}</div>
            </div>
          </div>

          <hr class="divider" />

          <form @submit.prevent="handleChangePassword" class="pw-form">
            <h3>Changer le mot de passe</h3>

            <div class="field">
              <label>Mot de passe actuel</label>
              <input
                v-model="currentPassword"
                type="password"
                placeholder="••••••••"
                autocomplete="current-password"
                :disabled="saving"
              />
            </div>

            <div class="field">
              <label>Nouveau mot de passe</label>
              <input
                v-model="newPassword"
                type="password"
                placeholder="••••••••"
                autocomplete="new-password"
                :disabled="saving"
              />
            </div>

            <div class="field">
              <label>Confirmer le nouveau mot de passe</label>
              <input
                v-model="confirmPassword"
                type="password"
                placeholder="••••••••"
                autocomplete="new-password"
                :disabled="saving"
              />
            </div>

            <div v-if="error" class="msg error">{{ error }}</div>
            <div v-if="success" class="msg success">Mot de passe modifié !</div>

            <button type="submit" class="btn-primary" :disabled="saving">
              <span v-if="saving" class="spinner" />
              <span v-else>Enregistrer</span>
            </button>
          </form>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useApi } from '../composables/useApi'

defineEmits(['close'])

const authStore = useAuthStore()
const { apiFetch } = useApi()

const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const saving = ref(false)
const error = ref('')
const success = ref(false)

async function handleChangePassword() {
  error.value = ''
  success.value = false

  if (newPassword.value.length < 8) {
    error.value = 'Le mot de passe doit faire au moins 8 caractères'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    error.value = 'Les mots de passe ne correspondent pas'
    return
  }

  saving.value = true
  try {
    const res = await apiFetch('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({
        current_password: currentPassword.value,
        new_password: newPassword.value,
      }),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || 'Erreur lors du changement de mot de passe')
    }
    success.value = true
    currentPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
  } catch (err) {
    error.value = err.message
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 1rem;
}

.modal {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  width: 100%;
  max-width: 420px;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1.25rem 1.5rem 1rem;
  border-bottom: 1px solid var(--border);
}

.modal-header h2 {
  font-size: 1rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  color: var(--text);
  margin: 0;
}

.close-btn {
  background: none;
  border: none;
  color: var(--text-dim);
  font-size: 1rem;
  cursor: pointer;
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
}

.close-btn:hover {
  color: var(--text);
  background: var(--bg-hover);
}

.modal-body {
  padding: 1.25rem 1.5rem 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.user-icon {
  font-size: 1.5rem;
}

.user-name {
  font-weight: 600;
  color: var(--text);
}

.user-email {
  font-size: 0.82rem;
  color: var(--text-dim);
}

.divider {
  border: none;
  border-top: 1px solid var(--border);
  margin: 0;
}

.pw-form {
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.pw-form h3 {
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-dim);
  margin: 0;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.field label {
  font-size: 0.78rem;
  color: var(--text-dim);
}

.field input {
  background: var(--input-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  font-family: inherit;
  font-size: 0.9rem;
  padding: 0.6rem 0.8rem;
  outline: none;
  transition: border-color 0.15s;
}

.field input:focus {
  border-color: var(--accent);
}

.field input:disabled {
  opacity: 0.6;
}

.msg {
  font-size: 0.83rem;
  border-radius: 6px;
  padding: 0.45rem 0.7rem;
}

.error {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
}

.success {
  color: #4caf50;
  background: color-mix(in srgb, #4caf50 12%, transparent);
  border: 1px solid color-mix(in srgb, #4caf50 30%, transparent);
}

.btn-primary {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  padding: 0.65rem;
  font-size: 0.88rem;
}

.spinner {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  display: inline-block;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
