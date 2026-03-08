<template>
  <div class="portfolio-widget">

    <!-- Header with collapse toggle -->
    <button class="widget-header" @click="collapsed = !collapsed">
      <span class="widget-icon">📈</span>
      <span class="widget-title">Portefeuille</span>
      <span class="widget-chevron" :class="{ rotated: collapsed }">▾</span>
    </button>

    <div v-if="!collapsed" class="widget-body">

      <!-- Loading / error -->
      <div v-if="loading" class="widget-status">Chargement…</div>
      <div v-else-if="error" class="widget-status error">{{ error }}</div>

      <!-- Positions list -->
      <template v-else>
        <div v-if="positions.length === 0" class="widget-status">Aucune position.</div>

        <div v-for="pos in positions" :key="pos.symbol" class="pos-row">
          <span class="pos-symbol" :title="pos.label || pos.symbol">{{ pos.symbol }}</span>

          <div class="pos-ctrl" title="Quantité">
            <button class="step-btn" @click="stepField(pos, 'shares', -1)">−</button>
            <input
              class="pos-input"
              type="number"
              min="0"
              step="1"
              :value="pos.shares"
              @change="e => updateField(pos, 'shares', e.target.value)"
              @keyup.enter="e => e.target.blur()"
            />
            <button class="step-btn" @click="stepField(pos, 'shares', 1)">+</button>
          </div>

          <div class="pos-ctrl" title="PRU (€)">
            <button class="step-btn" @click="stepField(pos, 'avg_price', -0.01)">−</button>
            <input
              class="pos-input"
              type="number"
              min="0"
              step="0.01"
              :value="pos.avg_price"
              @change="e => updateField(pos, 'avg_price', e.target.value)"
              @keyup.enter="e => e.target.blur()"
            />
            <button class="step-btn" @click="stepField(pos, 'avg_price', 0.01)">+</button>
          </div>

          <button class="pos-delete" @click="deletePosition(pos.symbol)" title="Supprimer">✕</button>
        </div>

        <!-- Add new position -->
        <form class="add-row" @submit.prevent="addPosition">
          <input
            v-model="newSymbol"
            class="pos-input symbol-input"
            placeholder="TICKER"
            maxlength="10"
            required
          />
          <input
            v-model.number="newShares"
            class="pos-input"
            type="number"
            min="0"
            step="any"
            placeholder="Qté"
            required
          />
          <input
            v-model.number="newPrice"
            class="pos-input"
            type="number"
            min="0"
            step="any"
            placeholder="PRU€"
            required
          />
          <button class="pos-add" type="submit" title="Ajouter">+</button>
        </form>
      </template>

    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useApi } from '../composables/useApi'

const positions = ref([])
const loading = ref(false)
const error = ref(null)
const collapsed = ref(false)

const newSymbol = ref('')
const newShares = ref('')
const newPrice = ref('')

async function fetchPortfolio() {
  const { apiFetch } = useApi()
  loading.value = true
  error.value = null
  try {
    const res = await apiFetch('/api/portfolio')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    positions.value = await res.json()
  } catch (e) {
    error.value = 'Erreur de chargement'
  } finally {
    loading.value = false
  }
}

async function stepField(pos, field, delta) {
  const current = field === 'shares' ? pos.shares : pos.avg_price
  const precision = field === 'avg_price' ? 2 : 0
  const newVal = Math.max(0, parseFloat((current + delta).toFixed(precision)))
  await updateField(pos, field, newVal)
}

async function updateField(pos, field, rawValue) {
  const value = parseFloat(rawValue)
  if (isNaN(value) || value < 0) return

  const body = {
    shares: field === 'shares' ? value : pos.shares,
    avg_price: field === 'avg_price' ? value : pos.avg_price,
    label: pos.label,
  }

  const { apiFetch } = useApi()
  try {
    const res = await apiFetch(`/api/portfolio/${pos.symbol}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) throw new Error()
    const updated = await res.json()
    const idx = positions.value.findIndex(p => p.symbol === pos.symbol)
    if (idx !== -1) positions.value[idx] = updated
  } catch {
    error.value = `Erreur sauvegarde ${pos.symbol}`
    setTimeout(() => { error.value = null }, 3000)
  }
}

async function deletePosition(symbol) {
  const { apiFetch } = useApi()
  try {
    const res = await apiFetch(`/api/portfolio/${symbol}`, { method: 'DELETE' })
    if (!res.ok) throw new Error()
    positions.value = positions.value.filter(p => p.symbol !== symbol)
  } catch {
    error.value = `Erreur suppression ${symbol}`
    setTimeout(() => { error.value = null }, 3000)
  }
}

async function addPosition() {
  const sym = newSymbol.value.trim().toUpperCase()
  if (!sym || !newShares.value || !newPrice.value) return

  const { apiFetch } = useApi()
  try {
    const res = await apiFetch(`/api/portfolio/${sym}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ shares: newShares.value, avg_price: newPrice.value }),
    })
    if (!res.ok) throw new Error()
    const created = await res.json()
    const idx = positions.value.findIndex(p => p.symbol === sym)
    if (idx !== -1) {
      positions.value[idx] = created
    } else {
      positions.value.push(created)
    }
    newSymbol.value = ''
    newShares.value = ''
    newPrice.value = ''
  } catch {
    error.value = `Erreur ajout ${sym}`
    setTimeout(() => { error.value = null }, 3000)
  }
}

onMounted(fetchPortfolio)
</script>

<style scoped>
.portfolio-widget {
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}

/* ── Header ── */
.widget-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.45rem 0.75rem;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-dim);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: 600;
  font-family: inherit;
}

.widget-header:hover {
  color: var(--text);
  background: var(--bg-hover);
}

.widget-icon { font-size: 0.85rem; }

.widget-title { flex: 1; text-align: left; }

.widget-chevron {
  transition: transform 0.15s;
  font-size: 0.9rem;
}
.widget-chevron.rotated { transform: rotate(-90deg); }

/* ── Body ── */
.widget-body {
  padding: 0.25rem 0.5rem 0.5rem;
}

.widget-status {
  font-size: 0.75rem;
  color: var(--text-dim);
  padding: 0.25rem 0.25rem;
}
.widget-status.error { color: #e05; }

/* ── Position rows ── */
.pos-row {
  display: grid;
  grid-template-columns: minmax(0, 2.5fr) 1fr 1fr auto;
  gap: 0.25rem;
  align-items: center;
  margin-bottom: 0.25rem;
}

.add-row {
  display: grid;
  grid-template-columns: 3fr 2fr 2fr 1fr;
  gap: 0.25rem;
  align-items: center;
  margin-bottom: 0.2rem;
}

/* ── Step control group ── */
.pos-ctrl {
  display: flex;
  align-items: center;
  gap: 2px;
}

.step-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 20px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--input-bg);
  color: var(--text-dim);
  font-size: 0.75rem;
  font-weight: 700;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
  line-height: 1;
}

.step-btn:hover {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 50%, transparent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}

.pos-symbol {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--accent);
  letter-spacing: 0.04em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pos-input {
  background: var(--input-bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-family: inherit;
  font-size: 0.72rem;
  padding: 0.2rem 0.3rem;
  width: 100%;
  text-align: right;
  min-width: 0;
}

.pos-input:focus {
  outline: none;
  border-color: var(--accent);
}

/* Hide native number spinners inside step groups */
.pos-ctrl .pos-input::-webkit-inner-spin-button,
.pos-ctrl .pos-input::-webkit-outer-spin-button {
  -webkit-appearance: none;
}
.pos-ctrl .pos-input {
  -moz-appearance: textfield;
  text-align: center;
  padding: 0.2rem 0.15rem;
  min-width: 0;
}

.symbol-input {
  text-align: left;
  text-transform: uppercase;
  font-weight: 700;
  color: var(--accent);
  letter-spacing: 0.04em;
}

.pos-delete,
.pos-add {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.75rem;
  line-height: 1;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
  flex-shrink: 0;
}

.pos-delete {
  color: var(--text-dim);
  background: none;
  border: 1px solid transparent;
}
.pos-delete:hover {
  color: #e05252;
  background: color-mix(in srgb, #e05252 12%, transparent);
  border-color: color-mix(in srgb, #e05252 30%, transparent);
}

.pos-add {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 40%, transparent);
  font-weight: 700;
  font-size: 0.9rem;
}
.pos-add:hover {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}
</style>
