import { defineStore } from 'pinia'
import { ref } from 'vue'

export const usePersonaStore = defineStore('persona', () => {
  const personas = ref([])
  const activePersonaId = ref('alita')

  async function fetchPersonas() {
    try {
      const res = await fetch('/api/personas')
      personas.value = await res.json()
      if (personas.value.length && !personas.value.find(p => p.id === activePersonaId.value)) {
        activePersonaId.value = personas.value[0].id
      }
    } catch (err) {
      console.error('fetchPersonas failed', err)
    }
  }

  function setActivePersona(id) {
    activePersonaId.value = id
  }

  function getActive() {
    return personas.value.find(p => p.id === activePersonaId.value) || null
  }

  return { personas, activePersonaId, fetchPersonas, setActivePersona, getActive }
})
