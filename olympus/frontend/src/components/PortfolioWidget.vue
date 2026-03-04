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
          <input
            class="pos-input"
            type="number"
            min="0"
            step="any"
            :value="pos.shares"
            @change="e => updateField(pos, 'shares', e.target.value)"
            @keyup.enter="e => e.target.blur()"
            title="Quantité"
          />
          <input
            class="pos-input"
            type="number"
            min="0"
            step="any"
            :value="pos.avg_price"
            @change="e => updateField(pos, 'avg_price', e.target.value)"
            @keyup.enter="e => e.target.blur()"
            title="PRU (€)"
          />
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

const positions = ref([])
const loading = ref(false)
const error = ref(null)
const collapsed = ref(false)

const newSymbol = ref('')
const newShares = ref('')
const newPrice = ref('')

async function fetchPortfolio() {
  loading.value = true
  error.value = null
  try {
    const res = await fetch('/api/portfolio')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    positions.value = await res.json()
  } catch (e) {
    error.value = 'Erreur de chargement'
  } finally {
    loading.value = false
  }
}

async function updateField(pos, field, rawValue) {
  const value = parseFloat(rawValue)
  if (isNaN(value) || value < 0) return

  const body = {
    shares: field === 'shares' ? value : pos.shares,
    avg_price: field === 'avg_price' ? value : pos.avg_price,
    label: pos.label,
  }

  try {
    const res = await fetch(`/api/portfolio/${pos.symbol}`, {
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
  try {
    const res = await fetch(`/api/portfolio/${symbol}`, { method: 'DELETE' })
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

  try {
    const res = await fetch(`/api/portfolio/${sym}`, {
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
.pos-row,
.add-row {
  display: grid;
  grid-template-columns: 3fr 2fr 2fr 1fr;
  gap: 0.25rem;
  align-items: center;
  margin-bottom: 0.2rem;
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

.symbol-input {
  text-align: left;
  text-transform: uppercase;
  font-weight: 700;
  color: var(--accent);
  letter-spacing: 0.04em;
}

.pos-delete {
  font-size: 0.65rem;
  color: var(--text-dim);
  background: none;
  border: none;
  cursor: pointer;
  padding: 0.2rem;
  border-radius: 3px;
  line-height: 1;
}
.pos-delete:hover { color: #e05; background: var(--bg-hover); }

.pos-add {
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--accent);
  background: none;
  border: 1px solid var(--accent);
  border-radius: 4px;
  cursor: pointer;
  padding: 0.15rem;
  line-height: 1;
}
.pos-add:hover { background: var(--accent); color: #fff; }
</style>
