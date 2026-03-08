<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-header">
        <h1>Olympus</h1>
        <p>Créer un compte</p>
      </div>

      <div v-if="!inviteToken" class="auth-error">
        Token d'invitation manquant. Demande un lien d'invitation à l'administrateur.
      </div>

      <form v-else @submit.prevent="handleRegister" class="auth-form">
        <div class="field">
          <label for="username">Nom d'utilisateur</label>
          <input
            id="username"
            v-model="username"
            type="text"
            placeholder="asmo"
            autocomplete="username"
            :disabled="loading"
            required
          />
        </div>

        <div class="field">
          <label for="email">Email</label>
          <input
            id="email"
            v-model="email"
            type="email"
            placeholder="asmo@homelab.local"
            autocomplete="email"
            :disabled="loading"
            required
          />
        </div>

        <div class="field">
          <label for="password">Mot de passe</label>
          <input
            id="password"
            v-model="password"
            type="password"
            placeholder="8 caractères minimum"
            autocomplete="new-password"
            :disabled="loading"
            required
          />
        </div>

        <div class="field">
          <label for="confirm">Confirmer le mot de passe</label>
          <input
            id="confirm"
            v-model="confirm"
            type="password"
            placeholder="••••••••"
            autocomplete="new-password"
            :disabled="loading"
            required
          />
        </div>

        <div v-if="error" class="auth-error">{{ error }}</div>

        <button type="submit" class="btn-primary auth-submit" :disabled="loading || !inviteToken">
          <span v-if="loading" class="spinner" />
          <span v-else>Créer le compte</span>
        </button>

        <p class="auth-link">
          Déjà un compte ?
          <a href="/login" @click.prevent="$router.push('/login')">Se connecter</a>
        </p>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const inviteToken = ref('')
const username = ref('')
const email = ref('')
const password = ref('')
const confirm = ref('')
const error = ref('')
const loading = ref(false)

onMounted(() => {
  inviteToken.value = route.query.token || ''
})

async function handleRegister() {
  error.value = ''
  if (password.value !== confirm.value) {
    error.value = 'Les mots de passe ne correspondent pas'
    return
  }
  loading.value = true
  try {
    const res = await fetch(`/auth/register?token=${encodeURIComponent(inviteToken.value)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        username: username.value,
        email: email.value,
        password: password.value,
        confirm_password: confirm.value,
      }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'Registration failed')
    authStore.accessToken = data.access_token
    await authStore.fetchMe()
    router.push('/')
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg);
  padding: 1rem;
}

.auth-card {
  width: 100%;
  max-width: 380px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 2.5rem 2rem;
}

.auth-header {
  text-align: center;
  margin-bottom: 2rem;
}

.auth-header h1 {
  font-size: 2.5rem;
  color: var(--accent);
  letter-spacing: 0.08em;
  margin-bottom: 0.25rem;
}

.auth-header p {
  color: var(--text-dim);
  font-size: 0.85rem;
  letter-spacing: 0.05em;
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 1.1rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.field label {
  font-size: 0.8rem;
  color: var(--text-dim);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.field input {
  background: var(--input-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  font-family: inherit;
  font-size: 0.95rem;
  padding: 0.65rem 0.9rem;
  outline: none;
  transition: border-color 0.15s;
  width: 100%;
}

.field input:focus { border-color: var(--accent); }
.field input:disabled { opacity: 0.6; }

.auth-error {
  font-size: 0.85rem;
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
}

.auth-submit {
  width: 100%;
  padding: 0.7rem;
  font-size: 0.9rem;
  letter-spacing: 0.05em;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 0.25rem;
}

.auth-link {
  text-align: center;
  font-size: 0.85rem;
  color: var(--text-dim);
}

.auth-link a {
  color: var(--accent);
  cursor: pointer;
  text-decoration: none;
}

.auth-link a:hover { text-decoration: underline; }

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  display: inline-block;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
